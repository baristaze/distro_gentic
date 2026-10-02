"""What a host runs: an `exec` item it claimed and its owner's ceilings let
through, through its own local transport, in the workspace it holds. The
output streams back a part at a time and the result is pushed once, each
with the hash the host declares of the bytes it sends. While the item runs
the host renews its lease, and a stop from the control stream ends the
command at once: the transport ends its whole process tree.

The host holds no key of the platform's. Its transport's record keeps how a
command ended without its output, and the platform keeps the output sealed
under the session's key."""

import asyncio
import base64
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from acme.apps.host.agent import ExecutorInterface
from acme.apps.host.ceilings import Ask
from acme.client.client import ApiClient, ApiError
from acme.client.types import ClaimedWorkView, ExecDetailView, OutputStream
from acme.infra.exceptions import InfraException
from acme.infra.transports import CommandSpec, RecordSeal, TransportInterface
from acme.infra.workspaces import IsolationMode, IsolationSpec, Workspace

log = logging.getLogger(__name__)

EXEC = "EXEC"
STOPS = frozenset({"cancel", "interrupt", "deadline", "revoke"})
"""The control messages that end an item. Each but `revoke` is answered
with how far the item got; a revoked lease is no longer the host's to
answer for."""


async def _kept_nowhere(data: bytes) -> bytes | None:
    """The host holds no session's key, so its record keeps no output."""
    return None


NO_SEAL = RecordSeal(seal=_kept_nowhere, open=_kept_nowhere)

ClientFactory = Callable[[], ApiClient]
"""A client that calls with the host's credential as it is now."""

Sink = Callable[[str, str], Awaitable[None]]


@dataclass
class Running:
    """One item while it is here: the operation in flight, what stopped it,
    and what it printed so far, for the result a stop answers with."""

    operation: asyncio.Future[dict[str, Any]] | None = None
    stopped: str | None = None
    printed: dict[str, list[str]] = field(default_factory=lambda: {"stdout": [], "stderr": []})


class ExecutorRelayImpl(ExecutorInterface):
    """`transports` names the transport that runs each isolation mode this
    host gives; an item at any other mode is refused, with nothing run.
    Output gathers for `flush_seconds`, or up to `part_bytes`, before it is
    sent as a part, and the lease is renewed every `renew_seconds`."""

    def __init__(
        self,
        client: ClientFactory,
        transports: Mapping[IsolationMode, TransportInterface],
        *,
        flush_seconds: float = 0.25,
        part_bytes: int = 32_000,
        renew_seconds: float = 20.0,
    ) -> None:
        self._client = client
        self._transports = dict(transports)
        self._flush_seconds = flush_seconds
        self._part_bytes = part_bytes
        self._renew_seconds = renew_seconds
        self._running: dict[UUID, Running] = {}

    async def run(self, item: ClaimedWorkView, ask: Ask) -> None:
        if item.kind != EXEC:
            log.warning("item %s (%s) has no executor on this host yet", item.id, item.kind)
            return
        item_id = UUID(str(item.payload["item_id"]))
        running = Running()
        self._running[item_id] = running
        try:
            await self._run(item_id, running)
        except ApiError as error:
            # The platform settled it meanwhile, or took the lease back: the
            # first settlement stands, and the host claims on.
            log.warning("item %s: %s", item_id, error)
        finally:
            self._running.pop(item_id, None)

    async def refuse(self, item: ClaimedWorkView, reasons: list[str]) -> None:
        """An item past its owner's ceilings is refused at once, so the run
        that sent it reads why instead of waiting out its lease."""
        if item.kind != EXEC:
            return
        item_id = UUID(str(item.payload["item_id"]))
        detail = "this host refused it: " + "; ".join(reasons)
        await self._push(item_id, _result(refused=("refused_by_host", 403), detail=detail))

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

    async def _run(self, item_id: UUID, running: Running) -> None:
        async with self._client() as client:
            detail = await client.exec_detail(item_id)
        spec = IsolationSpec.model_validate(detail.spec)
        transport = self._transports.get(spec.mode)
        if transport is None:
            why = f"this host runs no {spec.mode.value} workspace"
            await self._push(item_id, _result(refused=("capability_missing", 501), detail=why))
            return
        workspace = Workspace(
            id=detail.session_id, org_id=detail.org_id, spec=spec, location=detail.location
        )
        parts = _Parts(self._client, item_id, running, self._flush_seconds, self._part_bytes)
        renewal = asyncio.ensure_future(self._renew(item_id))
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
        await self._push(item_id, result)

    async def _renew(self, item_id: UUID) -> None:
        """Renews the lease while the item runs. A renewal refused means the
        lease is no longer the host's: the command ends, and nothing is
        pushed for it."""
        while True:
            await asyncio.sleep(self._renew_seconds)
            try:
                async with self._client() as client:
                    await client.extend_exec_lease(item_id)
            except ApiError as error:
                log.warning("item %s: its lease was not renewed: %s", item_id, error)
                self.stop(item_id, "revoke")
                return

    async def _push(self, item_id: UUID, result: dict[str, Any]) -> None:
        data = json.dumps(result, separators=(",", ":")).encode()
        try:
            async with self._client() as client:
                await client.push_exec_result(item_id, data)
        except ApiError as error:
            # Settled already, by its lease, a stop, or the sweep: the first
            # settlement stands.
            log.warning("item %s: its result was refused: %s", item_id, error)


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
