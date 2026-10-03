"""What a host runs: a workspace its pool asked it to prepare, and an
`exec` item it claimed, each once its owner's ceilings let it through. The
ceilings hold an item's fields and the host builds from its spec, so an
item whose spec asks other than its fields say is refused, with nothing
made or run. A prepare makes the workspace through the host's own provider
for the session's isolation and answers where it is, which binds the
session to this host. An `exec` item runs through its own local transport,
in the workspace it holds. The output streams back a part at a time and the
result is pushed once, each with the hash the host declares of the bytes it
sends. While the item runs
the host renews its lease, and a stop from the control stream ends the
command at once: the transport ends its whole process tree.

The host holds no key of the platform's. Its transport's record keeps how a
command ended without its output, and the platform keeps the output sealed
under the session's key."""

import asyncio
import base64
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from acme.apps.host.agent import ExecutorInterface
from acme.apps.host.ceilings import Ask
from acme.client.client import WIRE_FAILURES, ApiClient, ApiError
from acme.client.types import ClaimedWorkView, ExecDetailView, OutputStream
from acme.client.types import IsolationMode as HostIsolation
from acme.infra.exceptions import InfraException
from acme.infra.transports import CommandSpec, RecordSeal, TransportInterface
from acme.infra.workspaces import (
    EgressMode,
    IsolationMode,
    IsolationSpec,
    Workspace,
    WorkspaceProviderInterface,
)

log = logging.getLogger(__name__)

EXEC = "EXEC"
WORKSPACE = "WORKSPACE"
STOPS = frozenset({"cancel", "interrupt", "deadline", "revoke"})
"""The control messages that end an item. Each but `revoke` is answered
with how far the item got; a revoked lease is no longer the host's to
answer for."""

HOST_MODES: dict[IsolationMode, HostIsolation] = {
    IsolationMode.VM: HostIsolation.vm,
    IsolationMode.CONTAINER: HostIsolation.container,
    IsolationMode.HOST: HostIsolation.directory,
}
"""The engine's isolation modes a host runs, by the names its ceilings give
them. Any other mode names none."""


def unlike(ask: Ask, spec: IsolationSpec, reads: tuple[str, ...]) -> str | None:
    """Why the workspace the host would build differs from what its item
    asked, or None when it does not. The owner's ceilings held the item's
    fields; the host builds from its spec. So the spec is read as an ask, as
    the platform writes the fields from it: its isolation, its egress, and
    `reads`, the paths on the host its result reads. A spec that differs is
    refused, so no payload widens what the host does past its ceilings."""
    match spec.egress.mode:
        case EgressMode.NONE:
            egress: frozenset[str] | None = frozenset()
        case EgressMode.ALLOWLIST:
            egress = frozenset(spec.egress.hosts)
        case EgressMode.OPEN:
            egress = None
    differs = [
        name
        for name, same in (
            ("isolation", HOST_MODES.get(spec.mode) == ask.isolation),
            ("egress", egress == ask.egress),
            ("reads", frozenset(reads) == frozenset(ask.reads)),
        )
        if not same
    ]
    if not differs:
        return None
    return f"its spec and its fields differ on {' and '.join(differs)}"


async def _kept_nowhere(data: bytes) -> bytes | None:
    """The host holds no session's key, so its record keeps no output."""
    return None


NO_SEAL = RecordSeal(seal=_kept_nowhere, open=_kept_nowhere)

ClientFactory = Callable[[], ApiClient]
"""A client that calls with the host's credential as it is now."""

Sink = Callable[[str, str], Awaitable[None]]


def outlasted(error: Exception) -> bool:
    """A failure the host waits out rather than reads as the platform's
    decision: an answer the API could not serve, a 429, or the wire."""
    if isinstance(error, ApiError):
        return error.status >= 500 or error.status == 429
    return isinstance(error, WIRE_FAILURES)


@dataclass
class Running:
    """One item while it is here: the operation in flight, what stopped it,
    and what it printed so far, for the result a stop answers with."""

    operation: asyncio.Future[dict[str, Any]] | None = None
    stopped: str | None = None
    held_until: float = 0.0  # when its lease ends, by this host's clock
    printed: dict[str, list[str]] = field(default_factory=lambda: {"stdout": [], "stderr": []})


class ExecutorRelayImpl(ExecutorInterface):
    """`transports` names the transport that runs each isolation mode this
    host gives; an item at any other mode is refused, with nothing run.
    Output gathers for `flush_seconds`, or up to `part_bytes`, before it is
    sent as a part, and the lease is renewed every `renew_seconds`, a
    third of the lease a renewal holds. A renewal or a result the platform
    fails to take is tried again within the lease, after a wait that starts
    at a quarter of a renewal's period and doubles."""

    def __init__(
        self,
        client: ClientFactory,
        transports: Mapping[IsolationMode, TransportInterface],
        workspaces: Mapping[IsolationMode, WorkspaceProviderInterface] | None = None,
        *,
        flush_seconds: float = 0.25,
        part_bytes: int = 32_000,
        renew_seconds: float = 20.0,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._client = client
        self._transports = dict(transports)
        self._workspaces = dict(workspaces or {})
        self._flush_seconds = flush_seconds
        self._part_bytes = part_bytes
        self._renew_seconds = renew_seconds
        self._lease_seconds = renew_seconds * 3
        self._jitter = jitter
        self._running: dict[UUID, Running] = {}

    async def run(self, item: ClaimedWorkView, ask: Ask) -> None:
        if item.kind == WORKSPACE:
            await self._workspace(item, ask)
            return
        if item.kind != EXEC:
            log.warning("item %s (%s) has no executor on this host yet", item.id, item.kind)
            return
        item_id = UUID(str(item.payload["item_id"]))
        running = Running(held_until=time.monotonic() + self._lease_seconds)
        self._running[item_id] = running
        try:
            await self._run(item_id, running, ask)
        except ApiError as error:
            # The platform settled it meanwhile, or took the lease back: the
            # first settlement stands, and the host claims on.
            log.warning("item %s: %s", item_id, error)
        finally:
            self._running.pop(item_id, None)

    async def refuse(self, item: ClaimedWorkView, reasons: list[str]) -> None:
        """An item past its owner's ceilings is refused at once, so the run
        that sent it reads why instead of waiting out its lease."""
        if item.kind == WORKSPACE:
            await self._answer(item.id, refused="this host refused it: " + "; ".join(reasons))
            return
        if item.kind != EXEC:
            return
        item_id = UUID(str(item.payload["item_id"]))
        detail = "this host refused it: " + "; ".join(reasons)
        held_until = time.monotonic() + self._lease_seconds
        await self._push(
            item_id, _result(refused=("refused_by_host", 403), detail=detail), held_until
        )

    def stop(self, item_id: UUID, kind: str) -> bool:
        """Ends the item at once if it is here: cancelling its operation ends
        the command's whole process tree, and one not started yet never
        starts."""
        running = self._running.get(item_id)
        if running is None or kind not in STOPS:
            return False
        running.stopped = running.stopped or kind
        if running.operation is not None:
            running.operation.cancel()
        return True

    async def _run(self, item_id: UUID, running: Running, ask: Ask) -> None:
        async with self._client() as client:
            detail = await client.exec_detail(item_id)
        spec = IsolationSpec.model_validate(detail.spec)
        reads = (detail.location,) if spec.mode is IsolationMode.HOST else ()
        differs = unlike(ask, spec, reads)
        if differs is not None:
            why = "this host refused it: " + differs
            refused = _result(refused=("refused_by_host", 403), detail=why)
            await self._push(item_id, refused, running.held_until)
            return
        transport = self._transports.get(spec.mode)
        if transport is None:
            why = f"this host runs no {spec.mode.value} workspace"
            refused = _result(refused=("capability_missing", 501), detail=why)
            await self._push(item_id, refused, running.held_until)
            return
        workspace = Workspace(
            id=detail.session_id, org_id=detail.org_id, spec=spec, location=detail.location
        )
        parts = _Parts(self._client, item_id, running, self._flush_seconds, self._part_bytes)
        renewal = asyncio.ensure_future(self._renew(item_id, running))
        result: dict[str, Any] | None = None
        try:
            if running.stopped is None:
                running.operation = asyncio.ensure_future(
                    _operate(transport, workspace, detail, parts.take)
                )
                await asyncio.wait({running.operation})
                result = _ended(running.operation)
        finally:
            renewal.cancel()
        await parts.flush()
        if running.stopped == "revoke":
            log.info("item %s: its lease was revoked, so nothing is pushed", item_id)
            return
        if result is None:
            result = _result(
                stopped=running.stopped or "cancel",
                stdout="".join(running.printed["stdout"]),
                stderr="".join(running.printed["stderr"]),
            )
        await self._push(item_id, result, running.held_until)

    async def _workspace(self, item: ClaimedWorkView, ask: Ask) -> None:
        """A prepare: the workspace made to the session's spec by this host's
        provider for its mode, and where it is answered. One whose spec
        differs from what it asked, or one this host cannot make, is answered
        as refused, so another host of the pool may. Where the workspace is
        made is the host's to choose, so a prepare reads no path of its own.
        When another host holds the session's workspace already, this one's
        goes. A release or a purge has no executor here yet."""
        payload = item.payload
        if payload.get("operation") != "prepare":
            log.warning(
                "item %s: a workspace %s has no executor here", item.id, payload.get("operation")
            )
            return
        try:
            spec = IsolationSpec.model_validate(payload["spec"])
            session_id = UUID(str(payload["session_id"]))
        except KeyError, ValueError, ValidationError:
            await self._answer(item.id, refused="the prepare names no session or spec")
            return
        differs = unlike(ask, spec, ())
        if differs is not None:
            await self._answer(item.id, refused="this host refused it: " + differs)
            return
        org_id = item.org_id
        provider = self._workspaces.get(spec.mode)
        if provider is None:
            await self._answer(item.id, refused=f"this host makes no {spec.mode.value} workspace")
            return
        try:
            workspace = await provider.prepare(org_id, session_id, spec)
        except InfraException as error:
            await self._answer(item.id, refused=error.message)
            return
        held = await self._answer(item.id, location=workspace.location)
        if held is False:
            log.info("item %s: another host holds the workspace, so this one goes", item.id)
            await provider.purge(org_id, session_id)

    async def _answer(
        self, item_id: UUID, *, location: str | None = None, refused: str | None = None
    ) -> bool | None:
        """A prepare's answer; whether the session's workspace is this host's,
        or None when the platform took no answer, and the work's lease is
        left to run out."""
        try:
            async with self._client() as client:
                answered = await client.answer_prepare(item_id, location=location, refused=refused)
        except (ApiError, *WIRE_FAILURES) as error:
            log.warning("item %s: its answer was not taken: %s", item_id, error)
            return None
        return answered.held

    async def _renew(self, item_id: UUID, running: Running) -> None:
        """Renews the lease while the item runs. A failure the host outlasts
        is tried again while the lease lasts. A renewal refused, or one that
        still fails when the lease ends, means the lease is no longer the
        host's: the command ends, and nothing is pushed for it."""
        while True:
            await asyncio.sleep(self._renew_seconds)
            try:
                await self._outlasting(
                    lambda client: client.extend_exec_lease(item_id), running.held_until
                )
            except (ApiError, *WIRE_FAILURES) as error:
                log.warning("item %s: its lease was not renewed: %s", item_id, error)
                self.stop(item_id, "revoke")
                return
            running.held_until = time.monotonic() + self._lease_seconds

    async def _push(self, item_id: UUID, result: dict[str, Any], held_until: float) -> None:
        """Pushes how the item ended, tried again while its lease lasts."""
        data = json.dumps(result, separators=(",", ":")).encode()
        try:
            await self._outlasting(
                lambda client: client.push_exec_result(item_id, data), held_until
            )
        except (ApiError, *WIRE_FAILURES) as error:
            # Settled already, by its lease, a stop, or the sweep: the first
            # settlement stands. One the platform never took is the sweep's.
            log.warning("item %s: its result was not taken: %s", item_id, error)

    async def _outlasting(
        self, call: Callable[[ApiClient], Awaitable[object]], until: float
    ) -> None:
        """`call`, with the host's credential as it is at each attempt. A
        failure the host outlasts is tried again after a wait that doubles,
        half of it jitter, or longer when the server asked; one that would
        land past `until`, by this host's clock, is raised, as a refusal is."""
        failures = 0
        while True:
            try:
                async with self._client() as client:
                    await call(client)
                return
            except (ApiError, *WIRE_FAILURES) as error:
                if not outlasted(error):
                    raise
                failures += 1
                full = self._renew_seconds / 4 * 2 ** (failures - 1)
                wait = full / 2 + (full / 2) * self._jitter()
                if isinstance(error, ApiError) and error.retry_after is not None:
                    wait = max(wait, error.retry_after)
                if time.monotonic() + wait >= until:
                    raise
                log.info("a call failed (%s); trying again in %.1fs", error, wait)
                await asyncio.sleep(wait)


async def _operate(
    transport: TransportInterface, workspace: Workspace, detail: ExecDetailView, on_output: Sink
) -> dict[str, Any]:
    """The one operation the item names, through the host's transport."""
    request = detail.request
    match request["operation"]:
        case "run":
            command = CommandSpec.model_validate(
                {
                    "argv": request["argv"],
                    "cwd": request.get("cwd", "."),
                    "env": request.get("env", []),
                    "secrets": request.get("secrets", []),
                    "key": detail.call_id,
                    "epoch": detail.epoch or 0,
                    "deadline": detail.deadline,
                    "max_output": request.get("max_output", 1_000_000),
                    "effect": detail.effect,
                }
            )
            ran = await transport.run(workspace, command, on_output, seal=NO_SEAL)
            return _result(
                exit_code=ran.exit_code,
                timed_out=ran.timed_out,
                truncated=ran.truncated,
                secrets=list(ran.secrets),
                stdout=ran.stdout,
                stderr=ran.stderr,
            )
        case "read_file":
            data = await transport.read_file(workspace, request["path"], request["max_bytes"])
            return _result(data=base64.b64encode(data).decode())
        case "write_file":
            data = base64.b64decode(request["data"])
            await transport.write_file(workspace, request["path"], data, detail.epoch or 0)
            return _result()
        case "list_files":
            entries = await transport.list_files(workspace, request["path"], request["limit"])
            return _result(entries=[entry.model_dump(mode="json") for entry in entries])
        case operation:
            return _result(refused=("validation_failed", 422), detail=f"no operation {operation!r}")


def _ended(operation: asyncio.Future[dict[str, Any]]) -> dict[str, Any] | None:
    """How the operation ended: its result, its transport's refusal, or None
    when a stop ended it."""
    if operation.cancelled():
        return None
    error = operation.exception()
    if isinstance(error, InfraException):
        return _result(refused=(error.code, error.http_status), detail=error.message)
    if error is not None:
        log.error("an exec operation failed", exc_info=error)
        return _result(refused=("host_failed", 500), detail=type(error).__name__)
    return operation.result()


class _Parts:
    """The output of one item, gathered and sent in order, a part at a time."""

    def __init__(
        self,
        client: ClientFactory,
        item_id: UUID,
        running: Running,
        flush_seconds: float,
        part_bytes: int,
    ) -> None:
        self._client = client
        self._item_id = item_id
        self._running = running
        self._flush_seconds = flush_seconds
        self._part_bytes = part_bytes
        self._seq = 0
        self._pending: list[tuple[str, str]] = []
        self._size = 0
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def take(self, stream: str, text: str) -> None:
        self._running.printed[stream].append(text)
        self._pending.append((stream, text))
        self._size += len(text)
        if time.monotonic() - self._last >= self._flush_seconds or self._size >= self._part_bytes:
            await self.flush()

    async def flush(self) -> None:
        async with self._lock:
            pending, self._pending, self._size = self._pending, [], 0
            self._last = time.monotonic()
            # A part is whole characters: at most four bytes each in UTF-8,
            # so a part of a quarter as many characters fits in its bytes.
            step = max(1, self._part_bytes // 4)
            for stream, text in _joined(pending):
                for start in range(0, len(text), step):
                    chunk = text[start : start + step].encode()
                    try:
                        async with self._client() as client:
                            await client.push_exec_part(
                                self._item_id, self._seq, OutputStream(stream), chunk
                            )
                    except ApiError as error:
                        log.warning("item %s: a part was refused: %s", self._item_id, error)
                    self._seq += 1


def _joined(pending: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Adjacent text of one stream, as one part."""
    joined: list[tuple[str, str]] = []
    for stream, text in pending:
        if joined and joined[-1][0] == stream:
            joined[-1] = (stream, joined[-1][1] + text)
        else:
            joined.append((stream, text))
    return joined


def _result(
    *,
    exit_code: int | None = None,
    timed_out: bool = False,
    truncated: bool = False,
    stopped: str | None = None,
    refused: tuple[str, int] | None = None,
    secrets: list[str] | None = None,
    stdout: str = "",
    stderr: str = "",
    data: str | None = None,
    entries: list[dict[str, Any]] | None = None,
    detail: str = "",
) -> dict[str, Any]:
    """An exec result as the platform reads it: how the item ended, in the
    clear, and what it printed or read, which the platform seals."""
    return {
        "outcome": {
            "exit_code": exit_code,
            "timed_out": timed_out,
            "truncated": truncated,
            "stopped": stopped,
            "refused": None if refused is None else refused[0],
            "refused_status": None if refused is None else refused[1],
            "secrets": secrets or [],
        },
        "output": {
            "stdout": stdout,
            "stderr": stderr,
            "data": data,
            "entries": entries or [],
            "detail": detail,
        },
    }
