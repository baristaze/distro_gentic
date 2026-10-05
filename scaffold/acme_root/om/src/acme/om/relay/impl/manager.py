import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from acme.infra.observability import OUTCOMES
from acme.infra.workspaces import IsolationSpec
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
from acme.om.placement.kinds import HOST
from acme.om.placement.rules import host_lane
from acme.om.placement.types.claimant import Claimant
from acme.om.placement.types.work import (
    ExecOperation,
    ExecPayload,
    WorkspaceOperation,
    WorkspacePayload,
)
from acme.om.projects import ProjectsManagerInterface
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
    PrepareAnswer,
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
    # How long a prepare a host refused waits before a host of the pool may
    # claim it again.
    prepare_retry: timedelta = timedelta(seconds=30)


def worker_of(host: HostIdentity) -> str:
    """The name the host's claims carry, as placement spells it."""
    return Claimant(kind=HOST, id=host.host_id, org_id=host.org_id, pool_id=host.pool_id).worker_id


def _copy(item: ExecItem, now: datetime, **update: Any) -> ExecItem:
    """The item's next version. What it carries may be a dump (the queue row
    a claim took), so it is validated whole."""
    return ExecItem.model_validate(
        {**item.model_dump(), **update, "updated_at": now, "version": item.version + 1}
    )


def _operation(row: WorkItem) -> WorkspaceOperation | None:
    """What a `workspace` row asks; None for a payload this build cannot
    read."""
    try:
        return WorkspacePayload.model_validate(row.payload).operation
    except ValidationError:
        return None


class RelayManagerImpl(RelayManagerInterface):
    def __init__(
        self,
        storage: RelayStorageInterface,
        work: WorkManagerInterface,
        steps: StepsManagerInterface,
        tenancy: TenancyManagerInterface,
        hosts: HostsManagerInterface,
        projects: ProjectsManagerInterface,
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
        self._projects = projects
        self._relay = relay
        self._seal = seal
        self._options = options
        self._clock = clock

    # Where a session's workspace is.

    async def bind_workspace(
        self, ctx: TenantContext, session_id: UUID, host_id: UUID, location: str
    ) -> WorkspaceBinding:
        return await self._bind(ctx, session_id, host_id, location, None)

    async def _bind(
        self,
        ctx: TenantContext,
        session_id: UUID,
        host_id: UUID,
        location: str,
        instance_of: UUID | None,
    ) -> WorkspaceBinding:
        """Binds the workspace under `session_id` to the host: a session's
        own, or an instance made for the session `instance_of` names, which
        is held to that session's pool."""
        ctx.require(Permission.WRITE)
        owner = instance_of or session_id
        placed = await self._hosts.placement_of(ctx, owner)
        if placed.pool is None:
            raise ValidationFailed(f"session {owner} runs in the cloud; no host holds it")
        status = await self._hosts.get_host(ctx, placed.pool.id, host_id)
        host = None if status is None else status.host
        if host is None or host.revoked_at is not None:
            raise ValidationFailed(f"host {host_id} is no live host of session {owner}'s pool")
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
                instance_of=instance_of,
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

    async def ask_prepare(self, ctx: TenantContext, session_id: UUID, spec: IsolationSpec) -> bool:
        ctx.require(Permission.WRITE)
        placed = await self._hosts.placement_of(ctx, session_id)
        if placed.pool is None:
            raise ValidationFailed(f"session {session_id} runs in the cloud; no host prepares it")
        if await self._asked_of(ctx, session_id, placed.pool.id):
            return False
        await self._ask_prepare(ctx, session_id, placed.pool.id, spec, None)
        OUTCOMES.labels(subsystem="relay", outcome="prepare_asked").inc()
        return True

    async def ask_instance(
        self, ctx: TenantContext, session_id: UUID, instance_id: UUID, spec: IsolationSpec
    ) -> None:
        ctx.require(Permission.WRITE)
        placed = await self._hosts.placement_of(ctx, session_id)
        if placed.pool is None:
            raise ValidationFailed(f"session {session_id} runs in the cloud; no host makes it")
        await self._ask_prepare(ctx, instance_id, placed.pool.id, spec, session_id)
        OUTCOMES.labels(subsystem="relay", outcome="instance_asked").inc()

    async def ask_purge(self, ctx: TenantContext, instance_id: UUID, spec: IsolationSpec) -> bool:
        ctx.require(Permission.WRITE)
        binding = await self._storage.read_binding(ctx.org_id, instance_id)
        if binding is None:
            latest = await self._work.latest_for_target(ctx, WorkKind.WORKSPACE, instance_id)
            if latest is not None and latest.status is WorkStatus.QUEUED:
                await self._work.end_queued(ctx, latest, "its run ended before a host made it")
            return False
        payload = WorkspacePayload(
            operation=WorkspaceOperation.PURGE,
            host_id=binding.host_id,
            session_id=instance_id,
            spec=spec,
        )
        await self._enqueue_workspace(ctx, instance_id, payload)
        OUTCOMES.labels(subsystem="relay", outcome="purge_asked").inc()
        return True

    async def holder(self, ctx: TenantContext, session_id: UUID) -> WorkspaceBinding | None:
        ctx.require(Permission.READ)
        binding = await self._storage.read_binding(ctx.org_id, session_id)
        if binding is None:
            return None
        placed = await self._hosts.placement_of(ctx, binding.instance_of or session_id)
        if placed.pool is None:
            return None
        status = await self._hosts.get_host(ctx, placed.pool.id, binding.host_id)
        live = status is not None and status.host.revoked_at is None and status.online
        return binding if live else None

    async def ask_release(self, ctx: TenantContext, session_id: UUID, spec: IsolationSpec) -> bool:
        ctx.require(Permission.WRITE)
        binding = await self._storage.read_binding(ctx.org_id, session_id)
        if binding is None:
            return False
        latest = await self._work.latest_for_target(ctx, WorkKind.WORKSPACE, session_id)
        if (
            latest is not None
            and latest.status in (WorkStatus.QUEUED, WorkStatus.CLAIMED)
            and _operation(latest) is WorkspaceOperation.RELEASE
        ):
            return False
        # Letting go runs and reads nothing, so it asks nothing of the host's
        # ceilings: only the spec, which names the provider that made it.
        payload = WorkspacePayload(
            operation=WorkspaceOperation.RELEASE,
            host_id=binding.host_id,
            session_id=session_id,
            spec=spec,
        )
        await self._enqueue_workspace(ctx, session_id, payload)
        OUTCOMES.labels(subsystem="relay", outcome="release_asked").inc()
        return True

    async def prepared(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, answer: PrepareAnswer
    ) -> WorkspaceBinding | None:
        ctx = await self._service(rctx, host.org_id)
        row, payload = await self._prepare_held(ctx, host, item_id)
        assert payload.session_id is not None  # `_prepare_held` holds it
        session_id = payload.session_id
        if answer.refused is not None:
            # Back to the pool's lane after a wait, for a host that can give
            # it; the loop waits on the resource meanwhile.
            log.info("host %s refused to prepare a workspace: %s", host.host_id, answer.refused)
            await self._work.defer(ctx, row, self._options.prepare_retry)
            OUTCOMES.labels(subsystem="relay", outcome="prepare_refused").inc()
            return None
        assert answer.location is not None  # the answer's own rule
        binding = await self._storage.read_binding(host.org_id, session_id)
        owner = payload.instance_of or session_id
        if (
            binding is None
            or binding.host_id == host.host_id
            or not await self._holds(ctx, owner, binding.host_id)
        ):
            binding = await self._bind(
                ctx, session_id, host.host_id, answer.location, payload.instance_of
            )
        try:
            await self._work.complete(ctx, row)
        except LeaseLost, NotFound:
            log.info("workspace item %s: its row was no longer held when it was answered", row.id)
        OUTCOMES.labels(subsystem="relay", outcome="prepared").inc()
        return binding

    async def released(self, rctx: RequestContext, host: HostIdentity, item_id: UUID) -> None:
        ctx = await self._service(rctx, host.org_id)
        row = await self._workspace_held(
            ctx, host, item_id, (WorkspaceOperation.RELEASE, WorkspaceOperation.PURGE)
        )
        try:
            await self._work.complete(ctx, row)
        except LeaseLost, NotFound:
            log.info("workspace item %s: its row was no longer held when it was answered", row.id)
        OUTCOMES.labels(subsystem="relay", outcome="released").inc()

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
        await self._enqueue(ctx, item, call.by_person, binding.instance_of or item.session_id)
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

    async def running(self, rctx: RequestContext, org_id: UUID, session_id: UUID) -> list[ExecItem]:
        await self._service(rctx, org_id)
        return await self._storage.read_running(org_id, session_id, self._options.call_items)

    async def interrupt_running(
        self, rctx: RequestContext, org_id: UUID, session_id: UUID, below: int | None
    ) -> list[ExecItem]:
        ctx = await self._service(rctx, org_id)
        running = await self._storage.read_running(org_id, session_id, self._options.call_items)
        answered: list[ExecItem] = []
        for item in running:
            if below is not None and not stale(item.epoch, below):
                continue
            outcome = ExecOutcome(stopped=StopKind.INTERRUPT)
            ended = await self._settle(ctx, item, outcome, revoke=True)
            if ended is not None:
                answered.append(ended)
                OUTCOMES.labels(subsystem="relay", outcome="interrupted").inc()
        return answered

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

    async def bindings(self, after: UUID | None) -> list[tuple[UUID, WorkspaceBinding]]:
        return await self._storage.read_bindings(after, self._options.sweep_batch)

    async def end_host(self, rctx: RequestContext, org_id: UUID, host_id: UUID) -> int:
        ctx = await self._service(rctx, org_id)
        ended = await self._work.end_open_on_lane(
            org_id, host_lane(host_id), "its host was revoked"
        )
        settled = 0
        for row in ended:
            if row.kind != WorkKind.EXEC:
                continue
            try:
                payload = ExecPayload.model_validate(row.payload)
            except ValidationError:
                continue
            item = await self._storage.read_item(org_id, payload.item_id)
            if item is None or item.state not in (ExecState.QUEUED, ExecState.RUNNING):
                continue
            # The host is told nothing: a revoked host's calls are refused.
            if await self._settle(ctx, item, ExecOutcome(stopped=StopKind.REVOKE)) is not None:
                settled += 1
                OUTCOMES.labels(subsystem="relay", outcome="interrupted").inc()
        return settled

    async def purge_session(self, org_id: UUID, session_id: UUID) -> None:
        # Its commands' queue rows end first: a row whose item is gone would
        # wait for good on the lane of a host that never claims again.
        await self._work.end_open_for_target(
            org_id, WorkKind.EXEC, session_id, "its session was purged"
        )
        while await self._storage.purge_session(org_id, session_id, self._options.purge_batch):
            pass

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    # Helpers.

    async def _ask_prepare(
        self,
        ctx: TenantContext,
        target: UUID,
        pool_id: UUID,
        spec: IsolationSpec,
        instance_of: UUID | None,
    ) -> None:
        """A prepare of the workspace under `target` on the pool's lane, held
        to the project of the session it is for."""
        # Where on the host it is made is the host's to choose, so a prepare
        # reads no path of the host's.
        isolation, egress, _ = asks(spec, "")
        project = await self._projects.project_of(ctx, instance_of or target)
        payload = WorkspacePayload(
            operation=WorkspaceOperation.PREPARE,
            pool_id=pool_id,
            session_id=target,
            spec=spec,
            isolation=isolation,
            egress=egress,
            project_id=None if project is None else project.id,
            instance_of=instance_of,
        )
        await self._enqueue_workspace(ctx, target, payload)

    async def _enqueue_workspace(
        self, ctx: TenantContext, target: UUID, payload: WorkspacePayload
    ) -> None:
        """`workspace` work for the workspace under `target`, on the lane its
        payload names."""
        now = self._clock()
        row = new_id()
        await self._work.enqueue(
            ctx,
            WorkItem(
                id=row,
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                kind=WorkKind.WORKSPACE,
                target_id=target,
                idempotency_key=row,
                request_id=ctx.request_id,
                traceparent=ctx.traceparent,
                payload=payload.model_dump(mode="json"),
                status=WorkStatus.QUEUED,
                available_at=now,
            ),
        )

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

    async def _asked_of(self, ctx: TenantContext, session_id: UUID, pool_id: UUID) -> bool:
        """Whether the session's prepare waits or runs on `pool_id`'s lane. One
        that waits on another pool's, as the session moved since, is ended,
        so no host of a pool it left makes it. One a host of that pool holds
        already is left to end: its host is no host of the session's pool,
        so the session never runs there. A release that waits is ended too:
        a prepare is asked only when no live host holds the workspace, so
        none is left for it to let go."""
        latest = await self._work.latest_for_target(ctx, WorkKind.WORKSPACE, session_id)
        if latest is None or latest.status not in (WorkStatus.QUEUED, WorkStatus.CLAIMED):
            return False
        try:
            asked_of = WorkspacePayload.model_validate(latest.payload).pool_id
        except ValidationError:
            asked_of = None
        if asked_of == pool_id:
            return True
        if latest.status is WorkStatus.QUEUED:
            await self._work.end_queued(ctx, latest, f"its session moved to pool {pool_id}")
        return False

    async def _prepare_held(
        self, ctx: TenantContext, host: HostIdentity, item_id: UUID
    ) -> tuple[WorkItem, WorkspacePayload]:
        """The prepare the host holds under a live claim, and what it asks:
        always a session's workspace, or an instance made for one."""
        row = await self._workspace_held(ctx, host, item_id, (WorkspaceOperation.PREPARE,))
        payload = WorkspacePayload.model_validate(row.payload)
        if payload.pool_id != host.pool_id or payload.session_id is None:
            raise ItemNotHeld(f"workspace item {item_id} is not held by this host")
        return row, payload

    async def _workspace_held(
        self,
        ctx: TenantContext,
        host: HostIdentity,
        item_id: UUID,
        operations: tuple[WorkspaceOperation, ...],
    ) -> WorkItem:
        """The workspace item of one of `operations` the host holds under a
        live claim. A release or a purge is the host's own, named in its
        payload."""
        try:
            row: WorkItem | None = await self._work.get_item(ctx, item_id)
        except NotFound:
            row = None
        held = (
            row is not None
            and row.kind == WorkKind.WORKSPACE
            and _operation(row) in operations
            and row.status is WorkStatus.CLAIMED
            and row.claimed_by == worker_of(host)
        )
        if held and WorkspaceOperation.PREPARE not in operations:
            assert row is not None
            held = WorkspacePayload.model_validate(row.payload).host_id == host.host_id
        if not held or row is None:
            raise ItemNotHeld(f"workspace item {item_id} is not held by this host")
        return row

    async def _holds(self, ctx: TenantContext, session_id: UUID, host_id: UUID) -> bool:
        """Whether the host is a live host of the session's pool: one that was
        neither revoked nor moved holds what it prepared, for the session or
        for an instance made for it."""
        placed = await self._hosts.placement_of(ctx, session_id)
        if placed.pool is None:
            return False
        status = await self._hosts.get_host(ctx, placed.pool.id, host_id)
        return status is not None and status.host.revoked_at is None

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
            binding = await self._storage.read_binding(ctx.org_id, item.session_id)
            owner = item.session_id if binding is None else binding.instance_of or item.session_id
            await self._enqueue(ctx, written, call.by_person, owner)
            return written
        newer = call.epoch is not None and (item.epoch is None or item.epoch < call.epoch)
        if item.state is ExecState.QUEUED and newer:
            # The run that holds the session now takes the command no host
            # took yet, so the claim does not refuse it as a lost run's.
            taken = _copy(item, now, epoch=call.epoch, deadline=call.deadline)
            written = await self._storage.write_item(ctx.org_id, taken, item.version)
            return written or await self._item(ctx.org_id, item.id)
        return item

    async def _enqueue(
        self, ctx: TenantContext, item: ExecItem, by_person: bool, owner: UUID
    ) -> None:
        """The item's queue row, on the lane of the host that holds the
        workspace. An unsafe one is claimed once: a lost lease fails it in
        the queue's own sweep, never back to the queue. It names the
        project of `owner`, the session the workspace is or was made for,
        which a host's owner may hold its work to, and whether a person sent
        it by hand, which the owner may refuse."""
        isolation, egress, reads = asks(item.spec, item.location)
        project = await self._projects.project_of(ctx, owner)
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
            by_person=by_person,
            project_id=None if project is None else project.id,
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
