"""What a host runs: a workspace its pool asked it to prepare, and an
`exec` item it claimed, each once its owner's ceilings let it through. The
ceilings hold an item's fields and the host builds from its spec, so an
item whose spec asks other than its fields say is refused, with nothing
made or run. A prepare makes the workspace through the host's own provider
for the session's isolation and answers where it is, which binds the
session to this host; a release lets its instance go and keeps its
files, and a purge destroys an instance and its files. A workspace kept by
snapshots keeps them in the host's own store, inside its owner's wall: a
snapshot takes back what the broker attached, is refused when it holds a
value of the host's secrets, and is answered by its reference, its digest,
and its size, never its bytes; a prepare that names one starts the
workspace from it, replaced whole, once its bytes match their digest; an
erase lets a session's go. A level whose snapshots the host's probe did not
show is refused for a workspace kept by snapshots, and for one on a base:
a prepare on a base with setup starts the workspace from the base this
host built and keeps in its own store (`acme.apps.host.bases`), and one
whose base failed to build is answered `unbuilt`, with the reason. An `exec` item
runs through its own local transport, in the workspace it holds,
prepared again first, on its base when it has one, so an instance that
stopped since starts anew over its files. The output streams back a part
at a time and the result is pushed once, each with the hash the host
declares of the bytes it sends. From its claim until its result, its
detail's read and its prepare included, the host renews its lease, and a
stop from the control stream ends the command at once: the transport ends
its whole process tree.

No file and no output crosses in an item or its result. A write's file is
downloaded from the store, checked against its size and its digest, and
only then written into the workspace; a read's file and what an item
printed or listed are uploaded to the store as objects (`objects.py`), and
the result names them by their size and their digest, so it is a few KiB,
sent as UTF-8 JSON. The lease is renewed until the result is pushed, the
transfers included.

The host holds no key of the platform's: an item's detail hands it the
key of each object it moves, which opens that object alone. Its
transport's record keeps how a command ended without its output, and the
platform keeps the output sealed."""

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from acme.apps.host.agent import ExecutorInterface
from acme.apps.host.bases import BaseUnbuilt, HostBases
from acme.apps.host.ceilings import Ask
from acme.apps.host.mcp import HostServers
from acme.apps.host.objects import HostObjects, PartRefused, Spooled, removed
from acme.apps.host.snapshots import HostSnapshots, SnapshotHeldSecret, SnapshotLost
from acme.client.client import ApiClient
from acme.client.transport import WIRE_FAILURES, ApiError
from acme.client.types.exec_relay import ExecDetailView, OutputStream
from acme.client.types.hosts import ClaimedWorkView
from acme.client.types.hosts import IsolationMode as HostIsolation
from acme.infra.agent_workspaces import (
    AgentWorkspace,
    AgentWorkspaceLost,
    AgentWorkspaceProviderInterface,
    Durability,
    EgressMode,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
)
from acme.infra.exceptions import InfraException
from acme.infra.transports import (
    CapabilityMissing,
    CommandSpec,
    CredentialBrokerInterface,
    RecordSeal,
    TransportInterface,
    WritesFromFile,
    secret_held,
)
from acme.timing import Every, Retries, RetryPolicy

log = logging.getLogger(__name__)

EXEC = "EXEC"
WORKSPACE = "WORKSPACE"
MCP_CALL = "mcp_call"
"""The operation of an `exec` item that calls a tool of a server this host
runs (`mcp.HostServers`)."""
PUSH_BYTES = 128_000
PUSH_PARTS = 256
"""The most bytes of output, and the most parts, one push carries, as the
platform bounds a push."""
DETAIL_CHARS = 1000
"""The most characters of why the host refused an item a result carries, as
the platform bounds it."""
NOT_SENT = (ApiError, InfraException, PartRefused, *WIRE_FAILURES)
"""What a transfer of an object raises when it gives up: the item's result
then says so, and is pushed."""
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


def unlike(
    ask: Ask, spec: IsolationSpec, reads: tuple[str, ...], *, building: bool = False
) -> str | None:
    """Why the workspace the host would build differs from what its item
    asked, or None when it does not. The owner's ceilings held the item's
    fields; the host builds from its spec. So the spec is read as an ask, as
    the platform writes the fields from it: its isolation, its egress, and
    `reads`, the paths on the host its result reads. A prepare that may
    build its base first (`building`) asks for open egress when its setup
    has it. A spec that differs is refused, so no payload widens what the
    host does past its ceilings."""
    match spec.egress.mode:
        case EgressMode.NONE:
            egress: frozenset[str] | None = frozenset()
        case EgressMode.ALLOWLIST:
            egress = frozenset(spec.egress.hosts)
        case EgressMode.OPEN:
            egress = None
    base = spec.base
    if building and base is not None and base.setup and base.egress.mode is EgressMode.OPEN:
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
class Ended:
    """How an item ended here: its result as `_result` builds it, what it
    printed or listed included, and a read's file, spooled."""

    result: dict[str, Any]
    file: Spooled | None = None


@dataclass
class Running:
    """One item while it is here: the operation in flight, what stopped it,
    and what it printed so far, for the result a stop answers with."""

    operation: asyncio.Future[Ended] | None = None
    stopped: str | None = None
    held_until: float = 0.0  # when its lease ends, by this host's clock
    printed: dict[str, list[str]] = field(default_factory=lambda: {"stdout": [], "stderr": []})

    def lease_end(self) -> float:
        """When its lease ends as it was last renewed: what a transfer that
        outlasts one lease is tried again within."""
        return self.held_until


class ExecutorRelayImpl(ExecutorInterface):
    """`transports` names the transport that runs each isolation mode this
    host gives; an item at any other mode is refused, with nothing run.
    `kept_whole` names the modes a workspace kept by snapshots is held at
    with no snapshot of the host's: a VM of the cloud pool, whose pool
    keeps the VM's whole disk. Output gathers for `flush_seconds`, or up to
    `window_chars`, before the window is sent as one push, and the lease is
    renewed every `renew_seconds`, a
    third of the lease a renewal holds. A renewal or a result the platform
    fails to take is tried again within the lease, after a wait that starts
    at a quarter of a renewal's period and doubles, never past the lease, as
    a transfer of an object is. A transfer spools under `spool`, the host's
    own folder for it, or a temporary one made as it is first needed."""

    def __init__(
        self,
        client: ClientFactory,
        transports: Mapping[IsolationMode, TransportInterface],
        workspaces: Mapping[IsolationMode, AgentWorkspaceProviderInterface] | None = None,
        *,
        snapshots: HostSnapshots | None = None,
        snapshot_modes: Callable[[], frozenset[IsolationMode]] = frozenset,
        kept_whole: frozenset[IsolationMode] = frozenset(),
        broker: CredentialBrokerInterface | None = None,
        servers: HostServers | None = None,
        base_options: Mapping[str, Any] | None = None,
        spool: Path | None = None,
        flush_seconds: float = 0.25,
        window_chars: int = 32_000,
        renew_seconds: float = 20.0,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._client = client
        self._transports = dict(transports)
        self._agent_workspaces = dict(workspaces or {})
        self._snapshots = snapshots
        self._bases = (
            None
            if snapshots is None
            else HostBases(
                snapshots, self._agent_workspaces, self._transports, **(base_options or {})
            )
        )
        self._probed_snapshots = snapshot_modes
        self._kept_whole = kept_whole
        self._broker = broker
        self._servers = servers
        self._flush_seconds = flush_seconds
        self._window_chars = window_chars
        self._renew_seconds = renew_seconds
        self._lease_seconds = renew_seconds * 3
        # Half of each wait is jitter. The cap at the lease changes no wait
        # the host sleeps: the first wait it shortens comes once the waits
        # before it used most of the lease, and still lands past it.
        self._outlast = RetryPolicy(base=renew_seconds / 4, cap=self._lease_seconds, jitter=0.5)
        self._jitter = jitter
        self._objects = HostObjects(client, spool, self._outlast, jitter)
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
        refused = _small(_result(refused=("refused_by_host", 403), detail=detail))
        await self._push(item_id, refused, held_until)

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
        """Renews the item's lease from its claim until its result is pushed:
        the read of its detail may outlast a lease, as its prepare may, and
        so may the transfer of an object it moves."""
        renewal = asyncio.ensure_future(self._renew(item_id, running))
        ended = Ended(_result())
        try:
            detail, ended = await self._outcome(item_id, running, ask)
            if running.stopped == "revoke":
                log.info("item %s: its lease was revoked, so nothing is pushed", item_id)
                return
            result = await self._kept(item_id, detail, ended, running)
            if running.stopped == "revoke":
                log.info("item %s: its lease was revoked, so nothing is pushed", item_id)
                return
            await self._push(item_id, result, running.held_until)
        finally:
            renewal.cancel()
            if ended.file is not None:
                await removed(ended.file.path)

    async def _outcome(
        self, item_id: UUID, running: Running, ask: Ask
    ) -> tuple[ExecDetailView | None, Ended]:
        """How the item ended here, or why this host refused it, with the
        detail it was read by."""
        async with self._client() as client:
            detail = await client.exec_detail(item_id)
        spec = IsolationSpec.model_validate(detail.spec)
        reads = (detail.location,) if spec.mode is IsolationMode.HOST else ()
        differs = unlike(ask, spec, reads)
        if differs is not None:
            why = "this host refused it: " + differs
            return detail, Ended(_result(refused=("refused_by_host", 403), detail=why))
        if detail.request.get("operation") == MCP_CALL:
            return detail, await self._call_server(running, detail)
        transport = self._transports.get(spec.mode)
        if transport is None:
            why = f"this host runs no {spec.mode.value} workspace"
            return detail, Ended(_result(refused=("capability_missing", 501), detail=why))
        parts = _Parts(self._client, item_id, running, self._flush_seconds, self._window_chars)
        ended: Ended | None = None
        try:
            workspace = await self._held(detail, spec)
        except InfraException as error:
            ended = Ended(_result(refused=(error.code, error.http_status), detail=error.message))
        else:
            if running.stopped is None:
                running.operation = asyncio.ensure_future(
                    _operate(transport, self._objects, workspace, detail, parts.take)
                )
                await asyncio.wait({running.operation})
                ended = _ended(running.operation)
        await parts.flush()
        if ended is None:
            ended = Ended(
                _result(
                    stopped=running.stopped or "cancel",
                    stdout="".join(running.printed["stdout"]),
                    stderr="".join(running.printed["stderr"]),
                )
            )
        return detail, ended

    async def _kept(
        self, item_id: UUID, detail: ExecDetailView | None, ended: Ended, running: Running
    ) -> dict[str, Any]:
        """The result to push once the objects it names are in the store:
        what the item printed or listed, as its output, and a read's file,
        each uploaded and named by its size and its digest. An output that
        is not kept is said in the result; a read whose file is not sent is
        refused."""
        result = ended.result
        small = _small(result)
        if detail is None:
            return small
        output = result["output"]
        if detail.output is not None and result["outcome"]["refused"] is None:
            printed = json.dumps(
                {
                    "stdout": output["stdout"],
                    "stderr": output["stderr"],
                    "entries": output["entries"],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            try:
                size, digest = await self._objects.send(
                    item_id, "output", detail.output, printed, running.lease_end
                )
            except NOT_SENT as error:
                log.warning("item %s: its output was not kept: %s", item_id, error)
                small["detail"] = _cut(small["detail"] or f"its output was not kept: {error}")
            else:
                small["output"] = {"size": size, "digest": digest}
        if detail.file_out is not None and ended.file is not None:
            try:
                size, digest = await self._objects.send(
                    item_id, "file", detail.file_out, ended.file, running.lease_end
                )
            except NOT_SENT as error:
                log.warning("item %s: the file it read was not sent: %s", item_id, error)
                why = f"the file it read was not sent: {error}"
                return _small(_result(refused=("object_not_sent", 503), detail=why))
            small["file"] = {"size": size, "digest": digest}
        return small

    async def _call_server(self, running: Running, detail: ExecDetailView) -> Ended:
        """A call of a tool of a server this host runs: it needs no workspace
        and no transport. The server starts for the call, and a stop ends
        it with its process."""
        if running.stopped is None:
            running.operation = asyncio.ensure_future(self._answered(detail))
            await asyncio.wait({running.operation})
            ended = _ended(running.operation)
            if ended is not None:
                return ended
        return Ended(_result(stopped=running.stopped or "cancel"))

    async def _answered(self, detail: ExecDetailView) -> Ended:
        """The server's answer, its own word that the tool failed as an exit
        of 1, and the secret it carried, by name."""
        if self._servers is None:
            return Ended(
                _result(refused=("capability_missing", 501), detail="this host runs no MCP server")
            )
        try:
            answer = await self._servers.call(detail)
        except TimeoutError:
            return Ended(_result(timed_out=True, detail="the server did not answer in time"))
        used = self._servers.credential_of(str(detail.request.get("server", "")))
        return Ended(
            _result(
                exit_code=1 if answer.is_error else 0,
                stdout=answer.text,
                secrets=[used] if used is not None else [],
            )
        )

    async def _held(self, detail: ExecDetailView, spec: IsolationSpec) -> AgentWorkspace:
        """The workspace an item runs in, as this host holds it. One its own
        provider makes is prepared again first: a look while its instance
        runs, and a new instance over its files when it stopped, as after a
        reboot or a Docker restart, as a cloud loop's prepare does. One on a
        base with setup is prepared on the base this host keeps, so a new
        instance starts from it; none is built here, since an item's
        ceilings hold no setup's egress. One this host would make elsewhere
        than the platform says it is is refused."""
        provider = self._agent_workspaces.get(spec.mode)
        if provider is None:
            return AgentWorkspace(
                id=detail.agent_session_id,
                org_id=detail.org_id,
                spec=spec,
                location=detail.location,
            )
        base = None
        if spec.base is not None and spec.base.setup:
            if self._bases is not None:
                base = await self._bases.kept(detail.org_id, spec)
            if base is None:
                raise IsolationRefused(
                    f"this host keeps no base for session {detail.agent_session_id}'s workspace"
                )
        workspace = await provider.prepare(detail.org_id, detail.agent_session_id, spec, base=base)
        if workspace.location != detail.location:
            raise IsolationRefused(
                f"this host holds session {detail.agent_session_id}'s workspace at "
                f"{workspace.location}, not at {detail.location}"
            )
        return workspace

    async def _workspace(self, item: ClaimedWorkView, ask: Ask) -> None:
        """A prepare: the workspace made to the session's spec by this host's
        provider for its mode, and where it is answered. One whose spec
        differs from what it asked, or one this host cannot make, is answered
        as refused, so another host of the pool may. Where the workspace is
        made is the host's to choose, so a prepare reads no path of its own.
        One on a base with setup starts from the base this host keeps, built
        here first (`_base`). When another host holds the session's
        workspace already, this one's goes. A release lets an instance go
        (`_release`); a purge destroys one (`_purge`)."""
        payload = item.payload
        if payload.get("operation") == "release":
            await self._release(item)
            return
        if payload.get("operation") == "purge":
            await self._purge(item)
            return
        if payload.get("operation") == "snapshot":
            await self._snapshot(item)
            return
        if payload.get("operation") == "erase":
            await self._erase(item)
            return
        if payload.get("operation") != "prepare":
            log.warning(
                "item %s: a workspace %s has no executor here", item.id, payload.get("operation")
            )
            return
        try:
            spec = IsolationSpec.model_validate(payload["spec"])
            agent_session_id = UUID(str(payload["agent_session_id"]))
        except KeyError, ValueError, ValidationError:
            await self._answer(item.id, refused="the prepare names no session or spec")
            return
        # A prepare that restores no snapshot may build its base here first.
        differs = unlike(ask, spec, (), building=payload.get("snapshot") is None)
        if differs is not None:
            await self._answer(item.id, refused="this host refused it: " + differs)
            return
        org_id = item.org_id
        provider = self._agent_workspaces.get(spec.mode)
        if provider is None:
            await self._answer(item.id, refused=f"this host makes no {spec.mode.value} workspace")
            return
        if (
            spec.durability is Durability.SNAPSHOT
            and spec.mode not in self._snapshot_modes() | self._kept_whole
        ):
            # Never made as a cache in its stead: another host may keep it.
            why = f"this host has not probed snapshots of a {spec.mode.value} workspace"
            await self._answer(item.id, refused=why)
            return
        try:
            restore = await self._restore(item, spec)
        except SnapshotLost as lost:
            # This store does not hold it. The platform knows which host kept
            # it, so it decides whether another host may still restore it.
            await self._answer(item.id, refused=str(lost), lost=True)
            return
        base = None
        if restore is None and spec.base is not None and spec.base.setup:
            # A snapshot holds its base already; without one, the base is
            # read from this host's store, or built here.
            try:
                base = await self._base(org_id, spec)
            except BaseUnbuilt as unbuilt:
                await self._answer(item.id, refused=str(unbuilt), unbuilt=True)
                return
            except InfraException as error:
                await self._answer(item.id, refused=error.message)
                return
        try:
            workspace = await provider.prepare(
                org_id, agent_session_id, spec, snapshot=restore, base=base
            )
        except InfraException as error:
            lost_here = restore is not None and error.code == AgentWorkspaceLost.code
            if (
                base is not None
                and error.code == AgentWorkspaceLost.code
                and self._bases is not None
            ):
                # A base this host cannot bring in, such as one on an image
                # it no longer holds, holds nothing of the session's: it is
                # built again.
                await self._bases.drop(org_id, spec)
            await self._answer(item.id, refused=error.message, lost=lost_here)
            return
        held = await self._answer(item.id, location=workspace.location)
        if held is False:
            log.info("item %s: another host holds the workspace, so this one goes", item.id)
            await provider.purge(org_id, agent_session_id)

    async def _release(self, item: ClaimedWorkView) -> None:
        """A release: the instance this host's provider made for the session
        goes, and its files stay, so the session's next call here starts it
        anew over them. The platform pushed what its checkout held before it
        asked. An instance is found among what the provider holds, by the
        session and this host's tenant, so nothing else is let go, and one
        it no longer holds has nothing to let go. One that fails to go is
        not answered: its lease runs out, and it is claimed again."""
        try:
            spec = IsolationSpec.model_validate(item.payload["spec"])
            agent_session_id = UUID(str(item.payload["agent_session_id"]))
        except KeyError, ValueError, ValidationError:
            log.warning("item %s: the release names no session or spec", item.id)
            return
        provider = self._agent_workspaces.get(spec.mode)
        held = [] if provider is None else await provider.held_instances()
        for instance in held:
            if instance.id == agent_session_id and instance.org_id == item.org_id:
                assert provider is not None
                workspace = AgentWorkspace(
                    id=agent_session_id, org_id=item.org_id, spec=spec, location=instance.location
                )
                await provider.release(workspace)
                log.info(
                    "item %s: the instance of session %s is released", item.id, agent_session_id
                )
        try:
            async with self._client() as client:
                await client.answer_release(item.id)
        except (ApiError, *WIRE_FAILURES) as error:
            log.warning("item %s: its answer was not taken: %s", item.id, error)

    async def _purge(self, item: ClaimedWorkView) -> None:
        """A purge: the instance this host's provider made under the item's
        workspace id goes with its files, and its transport's records with
        it, so nothing of the run it served is left for another. Purging one
        already gone does nothing. One that fails to go is not answered: its
        lease runs out, and it is claimed again."""
        try:
            spec = IsolationSpec.model_validate(item.payload["spec"])
            instance_id = UUID(str(item.payload["agent_session_id"]))
        except KeyError, ValueError, ValidationError:
            log.warning("item %s: the purge names no workspace or spec", item.id)
            return
        provider = self._agent_workspaces.get(spec.mode)
        if provider is not None:
            await provider.purge(item.org_id, instance_id)
        transport = self._transports.get(spec.mode)
        if transport is not None:
            await transport.purge_records(instance_id)
        log.info("item %s: the instance %s is destroyed", item.id, instance_id)
        try:
            async with self._client() as client:
                await client.answer_release(item.id)
        except (ApiError, *WIRE_FAILURES) as error:
            log.warning("item %s: its answer was not taken: %s", item.id, error)

    async def _base(self, org_id: UUID, spec: IsolationSpec) -> bytes:
        """The base the workspace starts from, from this host's store or built
        here; a base is kept as a snapshot, so only at a level whose
        snapshots the probe showed."""
        if self._bases is None or spec.mode not in self._snapshot_modes():
            raise IsolationRefused(
                f"this host has not probed snapshots of a {spec.mode.value} workspace, "
                "which its base is kept by"
            )
        return await self._bases.archive(org_id, spec)

    def _snapshot_modes(self) -> frozenset[IsolationMode]:
        """The levels whose snapshots its probe showed; none without a
        store."""
        return frozenset() if self._snapshots is None else self._probed_snapshots()

    async def _restore(self, item: ClaimedWorkView, spec: IsolationSpec) -> bytes | None:
        """The bytes a prepare starts the workspace from: the snapshot it
        names, from this host's store, once they match their digest and
        their size; None for a prepare that names none. `SnapshotLost` when
        the store does not hold it, or holds other bytes."""
        named = item.payload.get("snapshot")
        if named is None:
            return None
        if self._snapshots is None or spec.mode not in self._snapshot_modes():
            raise SnapshotLost("this host keeps no snapshot store")
        try:
            reference = str(named["reference"])
            digest = str(named["digest"])
            size = int(named["size"])
        except KeyError, TypeError, ValueError:
            raise SnapshotLost("the prepare names no snapshot this store keeps") from None
        return await self._snapshots.load(reference, digest, size)

    async def _snapshot(self, item: ClaimedWorkView) -> None:
        """A snapshot: the live instance this host's provider holds for the
        session, by its labels, taken whole once the broker took back what
        it attached there, scanned for the host's secrets' values, and kept
        in this host's store: as the session's own, or, for a fork, as the
        child's it names (`kept_for`), so no erase of the session's
        snapshots reaches the child's copy. Answered by its reference, its
        digest, and its size, never its bytes, or by why none was kept."""
        try:
            spec = IsolationSpec.model_validate(item.payload["spec"])
            agent_session_id = UUID(str(item.payload["agent_session_id"]))
            snapshot_id = UUID(str(item.payload["snapshot"]["id"]))
            kept_for = item.payload.get("kept_for")
            owner = agent_session_id if kept_for is None else UUID(str(kept_for))
        except KeyError, TypeError, ValueError, ValidationError:
            await self._answer_snapshot(item.id, refused="the snapshot names no workspace")
            return
        provider = self._agent_workspaces.get(spec.mode)
        if provider is None or self._snapshots is None or spec.mode not in self._snapshot_modes():
            why = f"this host has not probed snapshots of a {spec.mode.value} workspace"
            await self._answer_snapshot(item.id, refused=why)
            return
        held = [
            instance
            for instance in await provider.held_instances()
            if instance.id == agent_session_id and instance.org_id == item.org_id
        ]
        if not held:
            why = f"this host holds no live instance of session {agent_session_id}'s workspace"
            await self._answer_snapshot(item.id, refused=why)
            return
        workspace = AgentWorkspace(
            id=agent_session_id, org_id=item.org_id, spec=spec, location=held[0].location
        )
        try:
            if self._broker is not None:
                await self._broker.detach_all(workspace)
            archive = await provider.snapshot(workspace)
            try:
                values = await self._snapshots.values(item.org_id)
                found = await secret_held(provider.held(archive), values)
                if found is not None:
                    raise SnapshotHeldSecret(
                        f"the workspace holds the secret {found!r}, so it is not kept"
                    )
                reference, digest, size = await self._snapshots.keep(
                    item.org_id, owner, snapshot_id, archive
                )
            except BaseException:
                await provider.discard(archive)
                raise
        except (InfraException, SnapshotHeldSecret, OSError) as error:
            why = error.message if isinstance(error, InfraException) else str(error)
            await self._answer_snapshot(item.id, refused=why)
            return
        log.info(
            "item %s: session %s's snapshot is kept as %s", item.id, agent_session_id, reference
        )
        await self._answer_snapshot(item.id, reference=reference, digest=digest, size=size)

    async def _erase(self, item: ClaimedWorkView) -> None:
        """An erase: every snapshot of the session in this host's store goes.
        One that fails is not answered: its lease runs out, and it is
        claimed again."""
        try:
            agent_session_id = UUID(str(item.payload["agent_session_id"]))
        except KeyError, ValueError:
            log.warning("item %s: the erase names no session", item.id)
            return
        if self._snapshots is not None:
            await self._snapshots.erase(item.org_id, agent_session_id)
        log.info("item %s: the snapshots of session %s are erased", item.id, agent_session_id)
        try:
            async with self._client() as client:
                await client.answer_release(item.id)
        except (ApiError, *WIRE_FAILURES) as error:
            log.warning("item %s: its answer was not taken: %s", item.id, error)

    async def _answer_snapshot(
        self,
        item_id: UUID,
        *,
        reference: str | None = None,
        digest: str | None = None,
        size: int | None = None,
        refused: str | None = None,
    ) -> None:
        try:
            async with self._client() as client:
                await client.answer_snapshot(
                    item_id, reference=reference, digest=digest, size=size, refused=refused
                )
        except (ApiError, *WIRE_FAILURES) as error:
            log.warning("item %s: its answer was not taken: %s", item_id, error)

    async def _answer(
        self,
        item_id: UUID,
        *,
        location: str | None = None,
        refused: str | None = None,
        lost: bool = False,
        unbuilt: bool = False,
    ) -> bool | None:
        """A prepare's answer; whether the session's workspace is this host's,
        or None when the platform took no answer, and the work's lease is
        left to run out."""
        try:
            async with self._client() as client:
                answered = await client.answer_prepare(
                    item_id, location=location, refused=refused, lost=lost, unbuilt=unbuilt
                )
        except (ApiError, *WIRE_FAILURES) as error:
            log.warning("item %s: its answer was not taken: %s", item_id, error)
            return None
        return answered.held

    async def _renew(self, item_id: UUID, running: Running) -> None:
        """Renews the lease while the item runs. A failure the host outlasts
        is tried again while the lease lasts. A renewal refused, or one that
        still fails when the lease ends, means the lease is no longer the
        host's: the command ends, and nothing is pushed for it."""
        async for _ in Every(self._renew_seconds, phase=self._renew_seconds):
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
        """Pushes how the item ended, tried again while its lease lasts: its
        JSON as UTF-8."""
        data = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
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
        retries = Retries(self._outlast, draw=self._jitter)
        while True:
            try:
                async with self._client() as client:
                    await call(client)
                return
            except (ApiError, *WIRE_FAILURES) as error:
                if not outlasted(error):
                    raise
                asked = error.retry_after if isinstance(error, ApiError) else None
                wait = retries.failed(asked)
                if time.monotonic() + wait >= until:
                    raise
                log.info("a call failed (%s); trying again in %.1fs", error, wait)
                await asyncio.sleep(wait)


async def _operate(
    transport: TransportInterface,
    objects: HostObjects,
    workspace: AgentWorkspace,
    detail: ExecDetailView,
    on_output: Sink,
) -> Ended:
    """The one operation the item names, through the host's transport. A
    read's file is spooled for its upload; a write's is downloaded and
    checked before a byte of it reaches the workspace."""
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
            return Ended(
                _result(
                    exit_code=ran.exit_code,
                    timed_out=ran.timed_out,
                    truncated=ran.truncated,
                    secrets=list(ran.secrets),
                    stdout=ran.stdout,
                    stderr=ran.stderr,
                )
            )
        case "read_file":
            if detail.file_out is None:
                raise CapabilityMissing("the read names no object to upload its file to")
            offset = request.get("offset", 0)
            spooled = await objects.spool_read(
                transport, workspace, request["path"], request["max_bytes"], offset
            )
            return Ended(_result(offset=offset), file=spooled)
        case "write_file":
            if detail.file_in is None or detail.url is None:
                raise CapabilityMissing("the write names no object to download its file from")
            if not isinstance(transport, WritesFromFile):
                raise CapabilityMissing(f"{transport.describe()} writes no file from disk")
            spooled = await objects.fetch(detail.file_in, detail.url)
            try:
                await transport.write_file_from(
                    workspace, request["path"], spooled.path, detail.epoch or 0
                )
            finally:
                await removed(spooled.path)
            return Ended(_result())
        case "list_files":
            entries = await transport.list_files(workspace, request["path"], request["limit"])
            return Ended(_result(entries=[entry.model_dump(mode="json") for entry in entries]))
        case operation:
            return Ended(
                _result(refused=("validation_failed", 422), detail=f"no operation {operation!r}")
            )


def _ended(operation: asyncio.Future[Ended]) -> Ended | None:
    """How the operation ended: its result, its transport's refusal, or None
    when a stop ended it."""
    if operation.cancelled():
        return None
    error = operation.exception()
    if isinstance(error, InfraException):
        return Ended(_result(refused=(error.code, error.http_status), detail=error.message))
    if error is not None:
        log.error("an exec operation failed", exc_info=error)
        return Ended(_result(refused=("host_failed", 500), detail=type(error).__name__))
    return operation.result()


class _Parts:
    """The output of one item, gathered and sent in order, a window at a
    time: one push holds every part a window gathered, a run of one stream's
    text each, unless it holds more than one push carries."""

    def __init__(
        self,
        client: ClientFactory,
        item_id: UUID,
        running: Running,
        flush_seconds: float,
        window_chars: int,
    ) -> None:
        self._client = client
        self._item_id = item_id
        self._running = running
        self._flush_seconds = flush_seconds
        self._window_chars = window_chars
        self._seq = 0
        self._pending: list[tuple[str, str]] = []
        self._size = 0
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def take(self, stream: str, text: str) -> None:
        self._running.printed[stream].append(text)
        self._pending.append((stream, text))
        self._size += len(text)
        if time.monotonic() - self._last >= self._flush_seconds or self._size >= self._window_chars:
            await self.flush()

    async def flush(self) -> None:
        async with self._lock:
            pending, self._pending, self._size = self._pending, [], 0
            self._last = time.monotonic()
            for push in self._pushes(_joined(pending)):
                try:
                    async with self._client() as client:
                        await client.push_exec_parts(self._item_id, push)
                except (ApiError, *WIRE_FAILURES) as error:
                    # A push lost on the wire is lost alone: the result
                    # carries the whole output, and is still pushed.
                    log.warning("item %s: a push was not taken: %s", self._item_id, error)

    def _pushes(self, runs: list[tuple[str, str]]) -> list[list[tuple[int, OutputStream, bytes]]]:
        """A window's runs as numbered parts, in pushes the platform takes:
        each of `PUSH_PARTS` parts and `PUSH_BYTES` bytes at most, a part
        cut only between whole characters."""
        pushes: list[list[tuple[int, OutputStream, bytes]]] = [[]]
        size = 0
        for stream, text in runs:
            data = text.encode()
            while data:
                cut = _whole(data, PUSH_BYTES - size)
                if cut == 0 or len(pushes[-1]) == PUSH_PARTS:
                    pushes.append([])
                    size = 0
                    continue
                pushes[-1].append((self._seq, OutputStream(stream), data[:cut]))
                self._seq += 1
                size += cut
                data = data[cut:]
        return [push for push in pushes if push]


def _whole(data: bytes, most: int) -> int:
    """How much of `data` fits in `most` bytes and ends on a character's
    boundary: a UTF-8 continuation byte never starts what is left."""
    if len(data) <= most:
        return len(data)
    cut = max(most, 0)
    while cut > 0 and data[cut] & 0xC0 == 0x80:
        cut -= 1
    return cut


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
    offset: int = 0,
    entries: list[dict[str, Any]] | None = None,
    detail: str = "",
) -> dict[str, Any]:
    """How an item ended here: its outcome, in the clear, and what it
    printed or listed, which goes as its output object (`_kept`). A read
    past the start echoes the offset it read from, which the runner checks;
    a read from the start carries none."""
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
            **({"offset": offset} if offset else {}),
            "entries": entries or [],
            "detail": detail,
        },
    }


def _small(result: dict[str, Any]) -> dict[str, Any]:
    """The result as the platform takes it: the outcome, why the host
    refused it, and the offset a read echoes, with no output in it."""
    output = result["output"]
    offset = output.get("offset", 0)
    return {
        "outcome": result["outcome"],
        "detail": _cut(output["detail"]),
        **({"offset": offset} if offset else {}),
    }


def _cut(detail: str) -> str:
    return detail if len(detail) <= DETAIL_CHARS else detail[: DETAIL_CHARS - 1] + "…"
