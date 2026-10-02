"""The runner's transports. The engine sees one transport interface; behind
it the runner picks, per session, by its placement: the direct transport to
a cloud workspace, or the relay into a customer's wall, where each
operation of a call travels as keyed `exec` work to the host that holds the
workspace and the runner waits for its result."""

import asyncio
import base64
import hashlib
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID

from acme.infra.exceptions import InfraException
from acme.infra.transports import (
    CapabilityMissing,
    CommandResult,
    CommandSpec,
    FileEntry,
    OutputSink,
    RecordSeal,
    StaleCommand,
    TransportInterface,
)
from acme.infra.workspaces import IsolationMode, Workspace
from acme.om.base import new_id, utcnow
from acme.om.context import RequestContext
from acme.om.exceptions import PlatformException, ToolFailed, Unavailable
from acme.om.placement.types.work import ExecEffect
from acme.om.relay.exceptions import ContentNotKept, NoWorkspaceHost, StaleExec
from acme.om.relay.manager import RelayManagerInterface
from acme.om.relay.types.exec import (
    REQUESTS,
    ExecCall,
    ExecItem,
    ExecOutcome,
    ExecOutput,
    ExecProgress,
    ExecRequest,
    ExecState,
    ListRequest,
    ReadRequest,
    RunRequest,
    StopKind,
    WriteRequest,
)
from acme.om.steps.types.header import ToolFailure
from acme.om.trust.placement import PlacementInterface

log = logging.getLogger(__name__)

SETTLED = frozenset({ExecState.DONE, ExecState.INTERRUPTED})


class HostRefused(InfraException):
    """An operation its host refused, before or as it ran, with the status
    and the code its transport refused it with there: a stale epoch, a path
    outside the workspace, an owner's ceiling. The engine reads it as it
    reads the same refusal from a transport of its own."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.http_status = status
        self.code = code


class TransportRelayImpl(TransportInterface):
    """Each operation of a call is an item whose id derives from the call's
    key (`rules.exec_id`), so a run that resumes the call meets the items
    it sent before: it attaches to an execution still running, or reads its
    stored result, and never starts a second. While it waits, the parts of
    the output stream to `on_output`. A run cancelled while it waits stops
    the item over its host's control stream; one whose deadline passes by
    this clock cuts it there.

    It runs below any context, so `relay` is the manager it reaches, bound
    at call time as the root builds it, and `stage` mints the request stage
    each operation runs under, at the edge of the process that wires it. A
    file operation carries no deadline of its own, so it takes
    `file_time`."""

    def __init__(
        self,
        relay: Callable[[], RelayManagerInterface],
        stage: Callable[[], RequestContext],
        *,
        file_time: timedelta = timedelta(minutes=5),
        grace: timedelta = timedelta(seconds=5),
        first_poll: timedelta = timedelta(milliseconds=50),
        last_poll: timedelta = timedelta(seconds=1),
        remembered: int = 4096,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._relay = relay
        self._stage = stage
        self._file_time = file_time
        self._grace = grace
        self._first_poll = first_poll
        self._last_poll = last_poll
        self._remembered = remembered
        self._sleep = sleep
        self._clock = clock
        # How many times each call sent each operation in this process, so
        # the same operation twice in one call is two items, and a run that
        # resumes the call meets them in the same order.
        self._sent: OrderedDict[tuple[UUID, str], int] = OrderedDict()

    async def run(
        self,
        workspace: Workspace,
        command: CommandSpec,
        on_output: OutputSink | None = None,
        *,
        seal: RecordSeal,
    ) -> CommandResult:
        request = RunRequest(
            argv=command.argv,
            cwd=command.cwd,
            env=command.env,
            secrets=command.secrets,
            max_output=command.max_output,
        )
        call = self._call(
            workspace, request, command.key, command.effect, command.deadline, command.epoch
        )
        progress = await self._through(workspace, call, self._occurrence(call), on_output)
        outcome, output = _ended(progress)
        if outcome.stopped is StopKind.DEADLINE:
            return CommandResult(
                key=command.key,
                exit_code=None,
                stdout=output.stdout,
                stderr=output.stderr,
                timed_out=True,
                truncated=outcome.truncated,
                secrets=outcome.secrets,
            )
        if outcome.stopped is not None:
            raise ToolFailed(
                ToolFailure.INTERRUPTED, f"the command was stopped by a {outcome.stopped.value}"
            )
        return _command_result(command.key, outcome, output)

    async def outcome(
        self, workspace: Workspace, key: UUID, epoch: int, *, seal: RecordSeal
    ) -> CommandResult | None:
        rctx = self._stage()
        try:
            item = await self._relay().outcome_of(rctx, workspace.org_id, workspace.id, key, epoch)
        except StaleExec as error:
            raise StaleCommand(error.message) from error
        if item is None:
            return None
        # Still running: the run attaches to it, and reads how it ends, while
        # its deadline and a grace allow.
        progress = await self._wait(rctx, workspace.org_id, item, None, item.epoch, attach=True)
        if progress is None or progress.state is not ExecState.DONE:
            return None
        outcome = progress.outcome or ExecOutcome()
        if outcome.stopped is not None or outcome.refused is not None:
            return None  # cut off before it ended, or never ran
        return _command_result(key, outcome, progress.output or ExecOutput())

    async def purge_records(self, workspace_id: UUID) -> None:
        """The relay's records of a session go with it in the sweep's purge;
        a host's own go with the workspace it holds."""
        return None

    async def read_file(self, workspace: Workspace, path: str, max_bytes: int) -> bytes:
        request = ReadRequest(path=path, max_bytes=max_bytes)
        progress = await self._file(workspace, request, "read_only", None)
        outcome, output = _ended(progress)
        _completed(outcome, output)
        return base64.b64decode(output.data or "")

    async def write_file(self, workspace: Workspace, path: str, data: bytes, epoch: int) -> None:
        request = WriteRequest(path=path, data=base64.b64encode(data).decode())
        progress = await self._file(workspace, request, "idempotent", epoch)
        _completed(*_ended(progress))

    async def list_files(self, workspace: Workspace, path: str, limit: int) -> list[FileEntry]:
        request = ListRequest(path=path, limit=limit)
        progress = await self._file(workspace, request, "read_only", None)
        outcome, output = _ended(progress)
        _completed(outcome, output)
        return list(output.entries)

    def describe(self) -> str:
        return "transport=relay"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    # Helpers.

    async def _file(
        self, workspace: Workspace, request: ExecRequest, effect: ExecEffect, epoch: int | None
    ) -> ExecProgress:
        """A file operation. The engine's carry no call's key, so each is an
        item keyed by itself: a read, or a whole file written under the
        run's epoch, which a repeat cannot harm."""
        call = self._call(
            workspace, request, new_id(), effect, self._clock() + self._file_time, epoch
        )
        return await self._through(workspace, call, 0, None)

    @staticmethod
    def _call(
        workspace: Workspace,
        request: ExecRequest,
        key: UUID,
        effect: ExecEffect,
        deadline: datetime,
        epoch: int | None,
    ) -> ExecCall:
        """One operation of a call in the session's workspace, which the
        engine prepares under the session's id."""
        return ExecCall(
            session_id=workspace.id,
            key=key,
            request=request,
            effect=effect,
            deadline=deadline,
            epoch=epoch,
            spec=workspace.spec,
        )

    async def _through(
        self,
        workspace: Workspace,
        call: ExecCall,
        occurrence: int,
        on_output: OutputSink | None,
    ) -> ExecProgress:
        epoch = call.epoch
        rctx = self._stage()
        org_id = workspace.org_id
        try:
            item = await self._relay().send(rctx, org_id, call, occurrence)
        except StaleExec as error:
            raise StaleCommand(error.message) from error
        except (NoWorkspaceHost, ContentNotKept) as error:
            raise CapabilityMissing(error.message) from error
        try:
            progress = await self._wait(rctx, org_id, item, on_output, epoch, attach=False)
        except asyncio.CancelledError:
            # The run stopped waiting: the item stops on its host at once.
            await asyncio.shield(self._stop(rctx, org_id, item.id, StopKind.CANCEL, epoch))
            raise
        assert progress is not None  # a wait that does not attach never gives up
        return progress

    async def _wait(
        self,
        rctx: RequestContext,
        org_id: UUID,
        item: ExecItem,
        on_output: OutputSink | None,
        epoch: int | None,
        *,
        attach: bool,
    ) -> ExecProgress | None:
        """Waits for the item to settle, streaming its parts. Past its
        deadline by this clock it is cut on its host; an attaching wait
        gives up a grace after that, and answers None.

        A read of its progress that fails for now is waited out until a
        grace past the deadline. One that fails for good, or still fails
        then, stops the item on its host, so nothing runs on that no call
        waits for: the call answers interrupted, and an attaching wait
        answers None."""
        after = -1
        delay = self._first_poll
        cut = False
        while True:
            try:
                progress = await self._relay().watch(rctx, org_id, item.id, after)
            except Exception as error:
                if _final(error) or self._clock() >= item.deadline + self._grace:
                    log.warning("exec item %s: its progress is lost", item.id, exc_info=True)
                    await self._stop(rctx, org_id, item.id, StopKind.INTERRUPT, epoch)
                    if attach:
                        return None
                    raise ToolFailed(
                        ToolFailure.INTERRUPTED,
                        "the platform lost track of the command while it ran, and stopped it; "
                        "check the workspace before you run it again",
                    ) from error
                log.warning("exec item %s: its progress was not read: %s", item.id, error)
            else:
                for part in progress.parts:
                    if on_output is not None:
                        await on_output(part.stream, part.text)
                    after = part.seq
                if progress.parts:
                    delay = self._first_poll
                    continue  # more may wait behind a full page
                if progress.state in SETTLED:
                    return progress
            now = self._clock()
            if not cut and now >= item.deadline:
                cut = True
                await self._stop(rctx, org_id, item.id, StopKind.DEADLINE, epoch)
            if attach and now >= item.deadline + self._grace:
                return None
            await self._sleep(delay.total_seconds())
            delay = min(delay * 2, self._last_poll)

    async def _stop(
        self, rctx: RequestContext, org_id: UUID, item_id: UUID, kind: StopKind, epoch: int | None
    ) -> None:
        """Stops the item; a stop the relay refuses, such as one from a run
        that lost the session, leaves the item to the run that holds it."""
        try:
            await self._relay().stop(rctx, org_id, item_id, kind, epoch)
        except Exception:
            log.warning("exec item %s: the %s was not sent", item_id, kind.value, exc_info=True)

    def _occurrence(self, call: ExecCall) -> int:
        digest = hashlib.sha256(REQUESTS.dump_json(call.request)).hexdigest()
        slot = (call.key, digest)
        seen = self._sent.pop(slot, -1) + 1
        self._sent[slot] = seen
        while len(self._sent) > self._remembered:
            self._sent.popitem(last=False)
        return seen


class TransportPlacedImpl(TransportInterface):
    """The runner's one transport: per session, the relay when its placement
    is inside its tenant's wall, and the direct transport otherwise. The
    engine and its tools see this alone, and never what is behind it."""

    def __init__(
        self,
        direct: TransportInterface,
        relayed: TransportInterface,
        placement: PlacementInterface,
    ) -> None:
        self._direct = direct
        self._relayed = relayed
        self._placement = placement

    async def run(
        self,
        workspace: Workspace,
        command: CommandSpec,
        on_output: OutputSink | None = None,
        *,
        seal: RecordSeal,
    ) -> CommandResult:
        transport = await self._for(workspace)
        return await transport.run(workspace, command, on_output, seal=seal)

    async def outcome(
        self, workspace: Workspace, key: UUID, epoch: int, *, seal: RecordSeal
    ) -> CommandResult | None:
        transport = await self._for(workspace)
        return await transport.outcome(workspace, key, epoch, seal=seal)

    async def purge_records(self, workspace_id: UUID) -> None:
        await self._direct.purge_records(workspace_id)
        await self._relayed.purge_records(workspace_id)

    async def read_file(self, workspace: Workspace, path: str, max_bytes: int) -> bytes:
        return await (await self._for(workspace)).read_file(workspace, path, max_bytes)

    async def write_file(self, workspace: Workspace, path: str, data: bytes, epoch: int) -> None:
        await (await self._for(workspace)).write_file(workspace, path, data, epoch)

    async def list_files(self, workspace: Workspace, path: str, limit: int) -> list[FileEntry]:
        return await (await self._for(workspace)).list_files(workspace, path, limit)

    def describe(self) -> str:
        return f"transport=placed({self._direct.describe()}, {self._relayed.describe()})"

    async def start(self) -> None:
        """The direct transport is infra's, which starts and closes it."""
        return None

    async def close(self) -> None:
        return None

    async def _for(self, workspace: Workspace) -> TransportInterface:
        """The transport of the workspace's session, by its placement. A
        session's workspace is prepared under the session's id. The absent
        workspace goes to the direct transport, which refuses it loudly."""
        if workspace.spec.mode is IsolationMode.NONE:
            return self._direct
        if await self._placement.inside_wall(workspace.org_id, workspace.id):
            return self._relayed
        return self._direct


def _final(error: Exception) -> bool:
    """A failure that waiting does not mend: the platform's refusal, never
    its `Unavailable`. A backend's or the wire's is waited out."""
    return isinstance(error, PlatformException) and not isinstance(error, Unavailable)


def _ended(progress: ExecProgress) -> tuple[ExecOutcome, ExecOutput]:
    """How a settled item ended, or the refusal of one that never ran."""
    outcome = progress.outcome or ExecOutcome()
    if progress.state is ExecState.INTERRUPTED:
        if outcome.refused == StaleExec.code:
            raise StaleCommand("the run that sent the command no longer holds the session")
        if outcome.stopped is not None:
            raise ToolFailed(
                ToolFailure.INTERRUPTED,
                f"the command was stopped by a {outcome.stopped.value} before a host ran it",
            )
        raise ToolFailed(
            ToolFailure.INTERRUPTED,
            "the host that ran the command was lost while it ran; its outcome is unknown, "
            "so check the workspace before you run it again",
        )
    return outcome, progress.output or ExecOutput()


def _completed(outcome: ExecOutcome, output: ExecOutput) -> None:
    """Refuses, as its host did, a file operation that did not complete."""
    if outcome.refused is not None:
        raise HostRefused(
            outcome.refused_status or 500, outcome.refused, output.detail or outcome.refused
        )
    if outcome.stopped is not None:
        raise ToolFailed(
            ToolFailure.INTERRUPTED, f"the operation was stopped by a {outcome.stopped.value}"
        )


def _command_result(key: UUID, outcome: ExecOutcome, output: ExecOutput) -> CommandResult:
    if outcome.refused is not None:
        raise HostRefused(
            outcome.refused_status or 500, outcome.refused, output.detail or outcome.refused
        )
    return CommandResult(
        key=key,
        exit_code=outcome.exit_code,
        stdout=output.stdout,
        stderr=output.stderr,
        timed_out=outcome.timed_out,
        truncated=outcome.truncated,
        secrets=outcome.secrets,
    )
