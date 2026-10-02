import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from acme.infra.observability import OUTCOMES
from acme.om.base import EMPTY_UUID, Platform, new_id, utcnow
from acme.om.context import Permission, RequestContext, TenantContext
from acme.om.exceptions import (
    InvalidCredential,
    LeaseLost,
    NotFound,
    PreconditionFailed,
    ValidationFailed,
)
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.types.host import HostIdentity
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import outbox_row, versioned_row
from acme.om.placement.types.claimant import Claimant, ClaimantKind
from acme.om.placement.types.work import ExecOperation, ExecPayload
from acme.om.relay.exceptions import ContentNotKept, ItemNotHeld, NoWorkspaceHost, StaleExec
from acme.om.relay.manager import RelayManagerInterface
from acme.om.relay.rules import (
    CONTROL_KIND,
    asks,
    claimed_row,
    exec_id,
    held_by,
    max_attempts,
    part_id,
    repeatable,
    resent,
    row_id,
    stale,
)
from acme.om.relay.storage import RelayStorageInterface
from acme.om.relay.types.exec import (
    REQUESTS,
    ExecCall,
    ExecControl,
    ExecDetail,
    ExecItem,
    ExecOutcome,
    ExecOutput,
    ExecPart,
    ExecProgress,
    ExecResult,
    ExecState,
    PartText,
    StopKind,
    WorkspaceBinding,
)
from acme.om.retention.crossing import Crossing, CrossingKind, CrossingRefused, verified
from acme.om.steps import StepsManagerInterface
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tools.seal import RecordSealInterface
from acme.om.work import WorkManagerInterface
from acme.om.work.types.work_item import WorkItem, WorkKind, WorkStatus

log = logging.getLogger(__name__)

BINDING_KIND = "relay.workspace_binding.updated"

STREAMS = frozenset({"stdout", "stderr"})


class RelayOptions(Platform):
    # How long a renewal holds an item: a host renews at a third of it, so
    # one missed renewal costs nothing and a lost host is known within it.
    lease: timedelta = timedelta(seconds=60)
    part_bytes: int = 64_000  # the most one part of output carries
    max_parts: int = 100_000  # the parts one run of an item streams, at most
    part_page: int = 200  # the parts one read takes
    call_items: int = 1000  # the items of one call a recovery reads, at most
    # How far back a host that reconnects is told its control messages again.
    control_window: timedelta = timedelta(hours=1)
    control_page: int = 500
    sweep_batch: int = 500
    purge_batch: int = 1000


def worker_of(host: HostIdentity) -> str:
    """The name the host's claims carry, as placement spells it."""
    return Claimant(
        kind=ClaimantKind.HOST, id=host.host_id, org_id=host.org_id, pool_id=host.pool_id
    ).worker_id


def _copy(item: ExecItem, now: datetime, **update: Any) -> ExecItem:
    """The item's next version. What it carries may be a dump (the queue row
    a claim took), so it is validated whole."""
    return ExecItem.model_validate(
        {**item.model_dump(), **update, "updated_at": now, "version": item.version + 1}
    )


class RelayManagerImpl(RelayManagerInterface):
    def __init__(
        self,
        storage: RelayStorageInterface,
        work: WorkManagerInterface,
        steps: StepsManagerInterface,
        tenancy: TenancyManagerInterface,
        hosts: HostsManagerInterface,
        relay: OutboxRelayInterface,
        seal: RecordSealInterface,
        options: RelayOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._work = work
        self._steps = steps
        self._tenancy = tenancy
        self._hosts = hosts
        self._relay = relay
        self._seal = seal
        self._options = options
        self._clock = clock

    # Where a session's workspace is.

    async def bind_workspace(
        self, ctx: TenantContext, session_id: UUID, host_id: UUID, location: str
    ) -> WorkspaceBinding:
        ctx.require(Permission.WRITE)
        placed = await self._hosts.placement_of(ctx, session_id)
        if placed.pool is None:
            raise ValidationFailed(f"session {session_id} runs in the cloud; no host holds it")
        statuses = await self._hosts.get_hosts(ctx, placed.pool.id)
        host = next((status.host for status in statuses if status.host.id == host_id), None)
        if host is None or host.revoked_at is not None:
            raise ValidationFailed(f"host {host_id} is no live host of session {session_id}'s pool")
        stored = await self._storage.read_binding(ctx.org_id, session_id)
        now = self._clock()
        if stored is None:
            binding = WorkspaceBinding(
                id=new_id(),
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                session_id=session_id,
                host_id=host.id,
                host_name=host.name,
                location=location,
            )
        else:
            binding = stored.model_copy(
                update={
                    "host_id": host.id,
                    "host_name": host.name,
                    "location": location,
                    "updated_at": now,
                    "updated_by": ctx.user_id,
                    "version": stored.version + 1,
                }
            )
        rows = (versioned_row(ctx, BINDING_KIND, session_id, binding.version),)
        expected = 0 if stored is None else stored.version
        await self._storage.write_binding(ctx.org_id, binding, expected, rows)
        await self._relay.relay_all(ctx.org_id, rows)
        return binding

    async def binding_of(self, ctx: TenantContext, session_id: UUID) -> WorkspaceBinding | None:
        ctx.require(Permission.READ)
        return await self._storage.read_binding(ctx.org_id, session_id)

    # The runner's side.

    async def send(
        self, rctx: RequestContext, org_id: UUID, call: ExecCall, occurrence: int
    ) -> ExecItem:
        ctx = await self._service(rctx, org_id)
        await self._admit(ctx, call.session_id, call.epoch)
        request = REQUESTS.dump_json(call.request)
        item_id = exec_id(call.key, request, occurrence)
        stored = await self._storage.read_item(org_id, item_id)
        if stored is not None:
            return await self._attach(ctx, stored, call)
        binding = await self._storage.read_binding(org_id, call.session_id)
        if binding is None:
            raise NoWorkspaceHost(
                f"session {call.session_id} is pinned to its tenant's hosts, and no host "
                "holds its workspace yet; its calls never run on the platform's machines"
            )
        sealed = await self._seal.seal(ctx, call.session_id, call.key, request)
        if sealed is None:
            raise ContentNotKept(
                f"session {call.session_id} keeps no content at rest, so its commands "
                "are not relayed into its tenant's wall"
            )
        now = self._clock()
        item = ExecItem(
            id=item_id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            session_id=call.session_id,
            key=call.key,
            operation=ExecOperation(call.request.operation),
            effect=call.effect,
            host_id=binding.host_id,
            location=binding.location,
            spec=call.spec,
            deadline=call.deadline,
            epoch=call.epoch,
            request=sealed,
            row_id=row_id(item_id, 1),
        )
        if not await self._storage.create_item(org_id, item):
            met = await self._storage.read_item(org_id, item_id)
            if met is None:
                raise NotFound(f"exec item {item_id} not found")
            return await self._attach(ctx, met, call)
        await self._enqueue(ctx, item)
        OUTCOMES.labels(subsystem="relay", outcome="sent").inc()
        return item

    async def watch(
        self, rctx: RequestContext, org_id: UUID, item_id: UUID, after_seq: int
    ) -> ExecProgress:
        ctx = await self._service(rctx, org_id)
        item = await self._item(org_id, item_id)
        parts = await self._storage.read_parts(
            org_id, item.row_id, after_seq, self._options.part_page
        )
        texts = [
            PartText(
                seq=part.seq, stream=part.stream, text=await self._opened(ctx, item, part.text)
            )
            for part in parts
        ]
        output = None
        if item.state is ExecState.DONE:
            opened = await self._opened(ctx, item, item.output)
            output = ExecOutput.model_validate_json(opened) if opened else ExecOutput()
        return ExecProgress(
            state=item.state, parts=tuple(texts), outcome=item.outcome, output=output
        )

    async def stop(
        self, rctx: RequestContext, org_id: UUID, item_id: UUID, kind: StopKind, epoch: int | None
    ) -> ExecItem:
        ctx = await self._service(rctx, org_id)
        item = await self._item(org_id, item_id)
        await self._admit(ctx, item.session_id, epoch)
        if item.state is ExecState.QUEUED:
            # No host took it: it never runs, and the row it left is
            # completed by the claim that finds it.
            stopped = await self._settle(ctx, item, ExecOutcome(stopped=kind))
            return stopped or await self._item(org_id, item_id)
        if item.state is ExecState.RUNNING:
            await self._control(ctx, item, kind)
        return item

    async def outcome_of(
        self, rctx: RequestContext, org_id: UUID, session_id: UUID, key: UUID, epoch: int
    ) -> ExecItem | None:
        ctx = await self._service(rctx, org_id)
        await self._admit(ctx, session_id, epoch)
        commands = [
            item
            for item in await self._storage.read_items_by_key(
                org_id, session_id, key, self._options.call_items
            )
            if item.operation is ExecOperation.RUN
        ]
        if not commands:
            return None
        command = commands[-1]
        if command.state is ExecState.QUEUED and stale(command.epoch, epoch):
            # The lost run's command, which no host took: it never runs now.
            outcome = ExecOutcome(refused=StaleExec.code, refused_status=StaleExec.http_status)
            return await self._settle(ctx, command, outcome) or await self._item(org_id, command.id)
        return command

    # A host's side.

    async def start(self, ctx: TenantContext, row: WorkItem) -> bool:
        try:
            payload = ExecPayload.model_validate(row.payload)
        except ValidationError:
            payload = None
        item = (
            None if payload is None else await self._storage.read_item(ctx.org_id, payload.item_id)
        )
        if (
            payload is None
            or item is None
            or item.row_id != row.id
            or item.host_id != payload.host_id
        ):
            await self._work.fail_for_good(ctx, row, "no exec item runs under this row")
            return False
        if item.state in (ExecState.DONE, ExecState.INTERRUPTED):
            await self._work.complete(ctx, row)
            return False
        if item.state is ExecState.RUNNING and not repeatable(item.effect):
            # A claim took it before, and how that run ended is unknown: an
            # unsafe item never runs twice.
            await self._settle(ctx, item, ExecOutcome(), revoke=True)
            await self._work.fail_for_good(ctx, row, "an unsafe exec item runs once")
            OUTCOMES.labels(subsystem="relay", outcome="unsafe_reclaimed").inc()
            return False
        cursor = await self._steps.get_cursor(ctx, item.session_id)
        if stale(item.epoch, cursor.epoch):
            outcome = ExecOutcome(refused=StaleExec.code, refused_status=StaleExec.http_status)
            await self._settle(ctx, item, outcome)
            await self._work.fail_for_good(ctx, row, "a command of a run that lost its session")
            OUTCOMES.labels(subsystem="relay", outcome="stale").inc()
            return False
        now = self._clock()
        started = _copy(
            item,
            now,
            state=ExecState.RUNNING,
            claim=row.model_dump(mode="json"),
            lease_expires_at=row.lease_expires_at,
        )
        if await self._storage.write_item(ctx.org_id, started, item.version) is None:
            # A stop or the sweep moved it meanwhile; the next claim decides.
            await self._work.release(ctx, row)
            return False
        return True

    async def detail(self, rctx: RequestContext, host: HostIdentity, item_id: UUID) -> ExecDetail:
        ctx = await self._service(rctx, host.org_id)
        item = await self._held(host, item_id)
        opened = await self._seal.open(ctx, item.session_id, item.key, item.request)
        if opened is None:
            raise NotFound(f"exec item {item_id}: its session's content is gone")
        return ExecDetail(
            item_id=item.id,
            key=item.key,
            org_id=host.org_id,
            session_id=item.session_id,
            effect=item.effect,
            deadline=item.deadline,
            epoch=item.epoch,
            spec=item.spec,
            location=item.location,
            request=REQUESTS.validate_json(opened),
        )

    async def push_part(
        self,
        rctx: RequestContext,
        host: HostIdentity,
        item_id: UUID,
        seq: int,
        stream: str,
        crossing: Crossing,
        data: bytes,
    ) -> None:
        # The bytes are checked against their hash before anything reads them.
        text = _decoded(_crossed(CrossingKind.STREAM_PART, crossing, data))
        if stream not in STREAMS:
            raise ValidationFailed(f"no stream {stream!r}; a part is stdout or stderr")
        if not 0 <= seq < self._options.max_parts or len(data) > self._options.part_bytes:
            raise ValidationFailed(
                f"a part is one of {self._options.max_parts} at most, "
                f"of {self._options.part_bytes} bytes at most"
            )
        ctx = await self._service(rctx, host.org_id)
        item = await self._held(host, item_id)
        sealed = await self._seal.seal(ctx, item.session_id, item.key, text.encode())
        part = ExecPart(
            id=part_id(item.row_id, seq),
            created_at=self._clock(),
            session_id=item.session_id,
            row_id=item.row_id,
            seq=seq,
            stream="stdout" if stream == "stdout" else "stderr",
            text=sealed,
            sha256=crossing.sha256,
        )
        await self._storage.add_part(host.org_id, part)

    async def push_result(
        self,
        rctx: RequestContext,
        host: HostIdentity,
        item_id: UUID,
        crossing: Crossing,
        data: bytes,
    ) -> ExecItem:
        # The bytes are checked against their hash before anything reads them.
        crossed = _crossed(CrossingKind.RESULT, crossing, data)
        try:
            result = ExecResult.model_validate_json(crossed)
        except ValidationError as error:
            raise ValidationFailed(f"a result that is no exec result: {error}"[:500]) from None
        ctx = await self._service(rctx, host.org_id)
        item = await self._held(host, item_id)
        sealed = await self._seal.seal(
            ctx, item.session_id, item.key, result.output.model_dump_json().encode()
        )
        now = self._clock()
        done = _copy(
            item,
            now,
            state=ExecState.DONE,
            outcome=result.outcome,
            output=sealed,
            result_sha256=crossing.sha256,
            settled_at=now,
            claim=None,
            lease_expires_at=None,
        )
        written = await self._storage.write_item(host.org_id, done, item.version)
        if written is None:
            raise ItemNotHeld(f"exec item {item_id} was settled before its result arrived")
        try:
            await self._work.complete(ctx, claimed_row(item))
        except LeaseLost, NotFound:
            # The result is the record; a row its lease left is the queue's
            # to settle, and a claim of it finds the item done.
            log.info("exec item %s: its row was no longer held when its result landed", item.id)
        OUTCOMES.labels(subsystem="relay", outcome="done").inc()
        return written

    async def extend(self, rctx: RequestContext, host: HostIdentity, item_id: UUID) -> datetime:
        ctx = await self._service(rctx, host.org_id)
        item = await self._held(host, item_id)
        renewed = await self._work.extend_lease(ctx, claimed_row(item), self._options.lease)
        held = _copy(
            item,
            self._clock(),
            claim=renewed.model_dump(mode="json"),
            lease_expires_at=renewed.lease_expires_at,
        )
        if await self._storage.write_item(host.org_id, held, item.version) is None:
            raise ItemNotHeld(f"exec item {item_id} was settled while its lease was renewed")
        assert renewed.lease_expires_at is not None  # a renewal sets it
        return renewed.lease_expires_at

    async def controls(
        self, rctx: RequestContext, host: HostIdentity, after: UUID | None
    ) -> list[ExecControl]:
        since = self._clock() - self._options.control_window
        return await self._storage.read_controls(
            host.org_id, host.host_id, after, since, self._options.control_page
        )

    # The sweep.

    async def settle_expired(self, rctx: RequestContext) -> int:
        expired = await self._storage.read_expired(self._clock(), self._options.sweep_batch)
        settled = 0
        for org_id, item in expired:
            try:
                ctx = await self._service(rctx, org_id)
            except InvalidCredential:
                continue  # a tenant that is gone: its purge takes its items
            if repeatable(item.effect):
                # Its row comes back to its host's lane, the one that holds
                # the workspace, and the next claim runs it again.
                now = self._clock()
                back = _copy(item, now, state=ExecState.QUEUED, claim=None, lease_expires_at=None)
                if await self._storage.write_item(org_id, back, item.version) is None:
                    continue
                await self._control(ctx, item, StopKind.REVOKE)
                OUTCOMES.labels(subsystem="relay", outcome="requeued").inc()
            else:
                if await self._settle(ctx, item, ExecOutcome(), revoke=True) is None:
                    continue
                OUTCOMES.labels(subsystem="relay", outcome="interrupted").inc()
            settled += 1
        return settled

    async def purge_session(self, org_id: UUID, session_id: UUID) -> None:
        while await self._storage.purge_session(org_id, session_id, self._options.purge_batch):
            pass

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    # Helpers.

    async def _service(self, rctx: RequestContext, org_id: UUID) -> TenantContext:
        """The tenant's service context: the relay runs below any principal,
        for the runner's transport and for a host, which is no person."""
        return await self._tenancy.service_context(rctx, org_id, EMPTY_UUID)

    async def _admit(self, ctx: TenantContext, session_id: UUID, epoch: int | None) -> None:
        """Refuses a run that no longer holds the session: nothing it sends,
        stops, or asks after acts."""
        if epoch is None:
            return
        cursor = await self._steps.get_cursor(ctx, session_id)
        if stale(epoch, cursor.epoch):
            OUTCOMES.labels(subsystem="relay", outcome="stale").inc()
            raise StaleExec(
                f"epoch {epoch} is below session {session_id}'s {cursor.epoch}: "
                "the run that sent it no longer holds the session"
            )

    async def _attach(self, ctx: TenantContext, item: ExecItem, call: ExecCall) -> ExecItem:
        """The item a call that sent it before meets: as it stands, so the
        run attaches to its execution or reads its result; or put on the
        queue again, when a repeat cannot harm it and its last run did not
        end its command."""
        if item.session_id != call.session_id:
            raise ValidationFailed(f"exec item {item.id} is another session's")
        now = self._clock()
        if resent(item):
            dispatch = item.dispatch + 1
            again = _copy(
                item,
                now,
                state=ExecState.QUEUED,
                dispatch=dispatch,
                row_id=row_id(item.id, dispatch),
                epoch=call.epoch,
                deadline=call.deadline,
                claim=None,
                lease_expires_at=None,
                outcome=None,
                output=None,
                result_sha256=None,
                settled_at=None,
            )
            written = await self._storage.write_item(ctx.org_id, again, item.version)
            if written is None:
                raise PreconditionFailed(f"exec item {item.id} moved while it was sent again")
            await self._enqueue(ctx, written)
            return written
        newer = call.epoch is not None and (item.epoch is None or item.epoch < call.epoch)
        if item.state is ExecState.QUEUED and newer:
            # The run that holds the session now takes the command no host
            # took yet, so the claim does not refuse it as a lost run's.
            taken = _copy(item, now, epoch=call.epoch, deadline=call.deadline)
            written = await self._storage.write_item(ctx.org_id, taken, item.version)
            return written or await self._item(ctx.org_id, item.id)
        return item

    async def _enqueue(self, ctx: TenantContext, item: ExecItem) -> None:
        """The item's queue row, on the lane of the host that holds the
        workspace. An unsafe one is claimed once: a lost lease fails it in
        the queue's own sweep, never back to the queue."""
        isolation, egress, reads = asks(item.spec, item.location)
        payload = ExecPayload(
            host_id=item.host_id,
            item_id=item.id,
            session_id=item.session_id,
            key=item.key,
            operation=item.operation,
            effect=item.effect,
            spec=item.spec,
            isolation=isolation,
            egress=egress,
            reads=reads,
        )
        now = self._clock()
        await self._work.enqueue(
            ctx,
            WorkItem(
                id=item.row_id,
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                kind=WorkKind.EXEC,
                target_id=item.session_id,
                idempotency_key=item.row_id,
                request_id=ctx.request_id,
                traceparent=ctx.traceparent,
                payload=payload.model_dump(mode="json"),
                status=WorkStatus.QUEUED,
                available_at=now,
                max_attempts=max_attempts(item.effect),
            ),
        )

    async def _settle(
        self, ctx: TenantContext, item: ExecItem, outcome: ExecOutcome, *, revoke: bool = False
    ) -> ExecItem | None:
        """Ends the item `interrupted` with `outcome`, if no one settled it
        first; with `revoke`, the host that held it is told to stop."""
        now = self._clock()
        ended = _copy(
            item,
            now,
            state=ExecState.INTERRUPTED,
            outcome=outcome,
            settled_at=now,
            claim=None,
            lease_expires_at=None,
        )
        written = await self._storage.write_item(ctx.org_id, ended, item.version)
        if written is not None and revoke:
            await self._control(ctx, item, StopKind.REVOKE)
        return written

    async def _control(self, ctx: TenantContext, item: ExecItem, kind: StopKind) -> None:
        """A control message for the host that holds the item; its row is
        the record, and its outbox row wakes the stream that carries it."""
        now = self._clock()
        control = ExecControl(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            session_id=item.session_id,
            item_id=item.id,
            host_id=item.host_id,
            kind=kind,
        )
        rows = (outbox_row(ctx, CONTROL_KIND, item.id, {"host_id": str(item.host_id)}),)
        await self._storage.add_control(ctx.org_id, control, rows)
        await self._relay.relay_all(ctx.org_id, rows)

    async def _item(self, org_id: UUID, item_id: UUID) -> ExecItem:
        item = await self._storage.read_item(org_id, item_id)
        if item is None:
            raise NotFound(f"exec item {item_id} not found")
        return item

    async def _held(self, host: HostIdentity, item_id: UUID) -> ExecItem:
        """The item, while this host holds it under its live claim."""
        item = await self._storage.read_item(host.org_id, item_id)
        if item is None or item.host_id != host.host_id or not held_by(item, worker_of(host)):
            raise ItemNotHeld(f"exec item {item_id} is not held by this host")
        return item

    async def _opened(self, ctx: TenantContext, item: ExecItem, sealed: bytes | None) -> str:
        """Sealed content of the item, opened; empty once its key is gone."""
        if sealed is None:
            return ""
        opened = await self._seal.open(ctx, item.session_id, item.key, sealed)
        return "" if opened is None else opened.decode()


def _crossed(kind: CrossingKind, crossing: Crossing, data: bytes) -> bytes:
    """The bytes, once they are the ones their sender declared, of the kind
    the route takes."""
    if crossing.kind is not kind:
        raise CrossingRefused(f"a {crossing.kind.value} sent as a {kind.value}")
    return verified(crossing, data)


def _decoded(data: bytes) -> str:
    try:
        return data.decode()
    except UnicodeDecodeError:
        raise ValidationFailed("a part of output is UTF-8 text") from None
