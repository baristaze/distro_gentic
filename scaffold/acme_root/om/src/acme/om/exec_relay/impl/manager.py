import asyncio
import base64
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from acme.infra.agent_workspaces import IsolationSpec
from acme.infra.buckets import Buckets, BucketsInterface
from acme.infra.buckets.sealed import (
    ObjectRefused,
    digest_of,
    new_key,
    open_object,
    seal_object,
    sealed_parts,
    sealed_size,
)
from acme.infra.exceptions import BlobNotFound, InfraException, UploadNotFound, UploadRefused
from acme.infra.observability import OUTCOMES
from acme.infra.streams import StreamBounds, StreamsInterface
from acme.om.agent_projects import AgentProjectsManagerInterface
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agent_workspaces.types.snapshot import HostSnapshot
from acme.om.base import EMPTY_UUID, OmBase, new_id, utcnow
from acme.om.context import AppType, Permission, RequestContext, TenantContext
from acme.om.exceptions import (
    InvalidCredential,
    LeaseLost,
    NotFound,
    PreconditionFailed,
    ValidationFailed,
)
from acme.om.exec_relay.exceptions import ContentNotKept, ItemNotHeld, NoWorkspaceHost, StaleExec
from acme.om.exec_relay.manager import ExecRelayManagerInterface
from acme.om.exec_relay.rules import (
    CONTROL_KIND,
    OBJECTS,
    OUTPUT_BYTES,
    PUSH_BYTES,
    PUSH_PARTS,
    asks,
    claimed_row,
    dispatch_objects,
    exec_id,
    held_by,
    max_attempts,
    object_reference,
    repeatable,
    resent,
    row_id,
    session_objects,
    setup_reaches,
    stale,
)
from acme.om.exec_relay.storage import ExecRelayStorageInterface
from acme.om.exec_relay.types.exec import (
    PARTS,
    REQUESTS,
    AgentWorkspaceBinding,
    ExecCall,
    ExecControl,
    ExecDetail,
    ExecItem,
    ExecOutcome,
    ExecOutput,
    ExecProgress,
    ExecRequest,
    ExecResult,
    ExecState,
    IssuedObjectPart,
    IssuedObjectUpload,
    ItemContent,
    ObjectKind,
    ObjectRef,
    ObjectSlot,
    PartText,
    PrepareAnswer,
    Printed,
    ReadRequest,
    ResultContent,
    SentPart,
    SnapshotAnswer,
    StopKind,
    StoredObject,
    WriteRequest,
)
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.types.host import HostIdentity
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, outbox_row, versioned_row
from acme.om.placement.kinds import HOST, PlacementWorkKind
from acme.om.placement.rules import host_lane
from acme.om.placement.types.claimant import Claimant
from acme.om.placement.types.work import (
    ExecOperation,
    ExecPayload,
    WorkspaceOperation,
    WorkspacePayload,
)
from acme.om.retention.crossing import Crossing, CrossingKind, CrossingRefused, verified
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tools.seal import RecordSealInterface
from acme.om.work import WorkManagerInterface
from acme.om.work.types.work_item import WorkItem, WorkStatus, work_row_kind

log = logging.getLogger(__name__)

BINDING_KIND = "exec_relay.agent_workspace_binding.updated"

BUCKET = Buckets.TOOL_OUTPUTS
"""Where the files the items move live while they cross: a session's tool
content, under its tenant and `rules.OBJECTS`."""
OCTETS = "application/octet-stream"

STREAMS = frozenset({"stdout", "stderr"})


class ExecRelayOptions(OmBase):
    # How long a renewal holds an item: a host renews at a third of it, so
    # one missed renewal costs nothing and a lost host is known within it.
    lease: timedelta = timedelta(seconds=60)
    max_parts: int = 100_000  # the parts one run of an item streams, at most
    # The live output of each run of an item, on the shared cache: a push is
    # one entry, and past the stream's entries or bytes the oldest goes. The
    # item's result holds it whole, so what the stream lets go is no loss.
    output: StreamBounds = StreamBounds()
    call_items: int = 1000  # the items of one call a recovery reads, at most
    # How far back a host that reconnects is told its control messages again.
    control_window: timedelta = timedelta(hours=1)
    control_page: int = 500
    sweep_batch: int = 500
    purge_batch: int = 1000
    # How long a prepare a host refused waits before a host of the pool may
    # claim it again.
    prepare_retry: timedelta = timedelta(seconds=30)
    # How long a URL signed for a host lets it start reading or sending its
    # item's object; a transfer under way finishes past it.
    object_ttl: timedelta = timedelta(minutes=15)
    parts_per_issue: int = 100  # the parts of an object one ask of a host signs


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


KeptOnHost = Callable[[TenantContext, UUID, HostSnapshot, UUID, UUID], Awaitable[None]]
"""Records a snapshot a host kept in its own store: given the host's
tenant's context, the session, the snapshot as the host answered it, the
host's pool, and the host."""

OPEN = (WorkStatus.QUEUED, WorkStatus.CLAIMED)
REFUSED = (WorkStatus.QUEUED, WorkStatus.CLAIMED, WorkStatus.FAILED)
"""Where a prepare a host refused stands: waiting for a host again, held
by one, or failed once its attempts were spent. Its reason stays with it."""


class ExecRelayManagerImpl(ExecRelayManagerInterface):
    """`kept` records each snapshot a host keeps; with none, every one a host
    answers is refused, since nothing could record where it lives. `buckets`
    holds the objects the items that move a file name, each sealed under a
    key of its own that the item keeps under the session's key."""

    def __init__(
        self,
        storage: ExecRelayStorageInterface,
        work: WorkManagerInterface,
        steps: AgentStepsManagerInterface,
        tenancy: TenancyManagerInterface,
        hosts: HostsManagerInterface,
        agent_projects: AgentProjectsManagerInterface,
        relay: OutboxRelayInterface,
        seal: RecordSealInterface,
        streams: StreamsInterface,
        buckets: BucketsInterface,
        options: ExecRelayOptions,
        clock: Callable[[], datetime] = utcnow,
        *,
        kept: KeptOnHost | None = None,
    ) -> None:
        self._kept = kept
        self._buckets = buckets
        self._storage = storage
        self._work = work
        self._steps = steps
        self._tenancy = tenancy
        self._hosts = hosts
        self._agent_projects = agent_projects
        self._relay = relay
        self._seal = seal
        self._streams = streams
        self._options = options
        self._clock = clock

    # Where a session's workspace is.

    async def bind_workspace(
        self, ctx: TenantContext, agent_session_id: UUID, host_id: UUID, location: str
    ) -> AgentWorkspaceBinding:
        return await self._bind(ctx, agent_session_id, host_id, location, None)

    async def _bind(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        host_id: UUID,
        location: str,
        instance_of: UUID | None,
    ) -> AgentWorkspaceBinding:
        """Binds the workspace under `agent_session_id` to the host: a session's
        own, or an instance made for the session `instance_of` names, which
        is held to that session's pool."""
        ctx.require(Permission.WRITE)
        owner = instance_of or agent_session_id
        placed = await self._hosts.work_placement(ctx, owner)
        if placed.pool is None:
            raise ValidationFailed(f"session {owner} runs in the cloud; no host holds it")
        status = await self._hosts.get_host(ctx, placed.pool.id, host_id)
        host = None if status is None else status.host
        if host is None or host.revoked_at is not None:
            raise ValidationFailed(f"host {host_id} is no live host of session {owner}'s pool")
        stored = await self._storage.read_binding(ctx.org_id, agent_session_id)
        now = self._clock()
        if stored is None:
            binding = AgentWorkspaceBinding(
                id=new_id(),
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                agent_session_id=agent_session_id,
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
        rows = (versioned_row(ctx, BINDING_KIND, agent_session_id, binding.version),)
        expected = 0 if stored is None else stored.version
        await self._storage.write_binding(ctx.org_id, binding, expected, rows)
        await self._relay.relay_all(ctx.org_id, rows)
        return binding

    async def binding_of(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentWorkspaceBinding | None:
        ctx.require(Permission.READ)
        return await self._storage.read_binding(ctx.org_id, agent_session_id)

    async def ask_prepare(
        self, ctx: TenantContext, agent_session_id: UUID, spec: IsolationSpec
    ) -> bool:
        ctx.require(Permission.WRITE)
        placed = await self._hosts.work_placement(ctx, agent_session_id)
        if placed.pool is None:
            raise ValidationFailed(
                f"session {agent_session_id} runs in the cloud; no host prepares it"
            )
        if await self._asked_of(ctx, agent_session_id, placed.pool.id):
            return False
        await self._ask_prepare(ctx, agent_session_id, placed.pool.id, spec, None)
        OUTCOMES.labels(subsystem="exec_relay", outcome="prepare_asked").inc()
        return True

    async def prepare_refusal(self, ctx: TenantContext, agent_session_id: UUID) -> str | None:
        ctx.require(Permission.READ)
        latest = await self._work.latest_for_target(
            ctx, PlacementWorkKind.WORKSPACE, agent_session_id
        )
        if latest is None or latest.status not in REFUSED or latest.last_error is None:
            return None
        try:
            payload = WorkspacePayload.model_validate(latest.payload)
        except ValidationError:
            return None
        if payload.operation is not WorkspaceOperation.PREPARE or payload.snapshot is not None:
            return None
        return latest.last_error

    async def ask_instance(
        self, ctx: TenantContext, agent_session_id: UUID, instance_id: UUID, spec: IsolationSpec
    ) -> None:
        ctx.require(Permission.WRITE)
        placed = await self._hosts.work_placement(ctx, agent_session_id)
        if placed.pool is None:
            raise ValidationFailed(
                f"session {agent_session_id} runs in the cloud; no host makes it"
            )
        await self._ask_prepare(ctx, instance_id, placed.pool.id, spec, agent_session_id)
        OUTCOMES.labels(subsystem="exec_relay", outcome="instance_asked").inc()

    async def ask_purge(self, ctx: TenantContext, instance_id: UUID, spec: IsolationSpec) -> bool:
        ctx.require(Permission.WRITE)
        binding = await self._storage.read_binding(ctx.org_id, instance_id)
        if binding is None:
            latest = await self._work.latest_for_target(
                ctx, PlacementWorkKind.WORKSPACE, instance_id
            )
            if latest is not None and latest.status is WorkStatus.QUEUED:
                await self._work.end_queued(ctx, latest, "its run ended before a host made it")
            return False
        payload = WorkspacePayload(
            operation=WorkspaceOperation.PURGE,
            host_id=binding.host_id,
            agent_session_id=instance_id,
            spec=spec,
        )
        await self._enqueue_workspace(ctx, instance_id, payload)
        OUTCOMES.labels(subsystem="exec_relay", outcome="purge_asked").inc()
        return True

    async def holder(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentWorkspaceBinding | None:
        ctx.require(Permission.READ)
        binding = await self._storage.read_binding(ctx.org_id, agent_session_id)
        if binding is None:
            return None
        placed = await self._hosts.work_placement(ctx, binding.instance_of or agent_session_id)
        if placed.pool is None:
            return None
        status = await self._hosts.get_host(ctx, placed.pool.id, binding.host_id)
        live = status is not None and status.host.revoked_at is None and status.online
        return binding if live else None

    async def ask_release(
        self, ctx: TenantContext, agent_session_id: UUID, spec: IsolationSpec
    ) -> bool:
        ctx.require(Permission.WRITE)
        binding = await self._storage.read_binding(ctx.org_id, agent_session_id)
        if binding is None:
            return False
        latest = await self._work.latest_for_target(
            ctx, PlacementWorkKind.WORKSPACE, agent_session_id
        )
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
            agent_session_id=agent_session_id,
            spec=spec,
        )
        await self._enqueue_workspace(ctx, agent_session_id, payload)
        OUTCOMES.labels(subsystem="exec_relay", outcome="release_asked").inc()
        return True

    async def ask_restore(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        snapshot: HostSnapshot,
    ) -> UUID:
        ctx.require(Permission.WRITE)
        placed = await self._hosts.work_placement(ctx, agent_session_id)
        if placed.pool is None:
            raise ValidationFailed(
                f"session {agent_session_id} runs in the cloud; no host restores it"
            )
        latest = await self._work.latest_for_target(
            ctx, PlacementWorkKind.WORKSPACE, agent_session_id
        )
        if latest is not None and latest.status in OPEN:
            try:
                waiting = WorkspacePayload.model_validate(latest.payload)
            except ValidationError:
                waiting = None
            if (
                waiting is not None
                and waiting.operation is WorkspaceOperation.PREPARE
                and waiting.snapshot is not None
                and waiting.snapshot.id == snapshot.id
                and waiting.pool_id == placed.pool.id
            ):
                return latest.id
            if latest.status is WorkStatus.QUEUED:
                await self._work.end_queued(ctx, latest, f"a restore of snapshot {snapshot.id}")
        # The host that holds the workspace replaces it, so no second one is
        # made beside it: while it is not revoked, the restore waits on its
        # lane, offline or not, as the workspace does. With none, any host of
        # the pool whose store keeps the snapshot makes it.
        binding = await self._storage.read_binding(ctx.org_id, agent_session_id)
        held_by = None
        if binding is not None and await self._holds(ctx, agent_session_id, binding.host_id):
            held_by = binding.host_id
        isolation, egress, _ = asks(spec, "")
        agent_project = await self._agent_projects.agent_project_of(ctx, agent_session_id)
        payload = WorkspacePayload(
            operation=WorkspaceOperation.PREPARE,
            pool_id=placed.pool.id,
            host_id=held_by,
            agent_session_id=agent_session_id,
            spec=spec,
            isolation=isolation,
            egress=egress,
            agent_project_id=None if agent_project is None else agent_project.id,
            snapshot=snapshot,
        )
        item_id = await self._enqueue_workspace(ctx, agent_session_id, payload)
        OUTCOMES.labels(subsystem="exec_relay", outcome="restore_asked").inc()
        return item_id

    async def ask_snapshot(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        snapshot_id: UUID,
        *,
        kept_for: UUID | None = None,
    ) -> UUID | None:
        ctx.require(Permission.WRITE)
        holder = await self.holder(ctx, agent_session_id)
        if holder is None:
            return None
        payload = WorkspacePayload(
            operation=WorkspaceOperation.SNAPSHOT,
            host_id=holder.host_id,
            agent_session_id=agent_session_id,
            spec=spec,
            snapshot=HostSnapshot(id=snapshot_id),
            kept_for=kept_for,
        )
        item_id = await self._enqueue_workspace(ctx, agent_session_id, payload)
        OUTCOMES.labels(subsystem="exec_relay", outcome="snapshot_asked").inc()
        return item_id

    async def ask_erase(self, ctx: TenantContext, agent_session_id: UUID, host_id: UUID) -> None:
        ctx.require(Permission.WRITE)
        payload = WorkspacePayload(
            operation=WorkspaceOperation.ERASE, host_id=host_id, agent_session_id=agent_session_id
        )
        await self._enqueue_workspace(ctx, agent_session_id, payload)
        OUTCOMES.labels(subsystem="exec_relay", outcome="erase_asked").inc()

    async def erase_purged(self, org_id: UUID, agent_session_id: UUID, host_id: UUID) -> None:
        # A purge runs below any principal, so the ask lands as the
        # machinery's, from a row of its own, on the lane of the host its
        # payload names.
        payload = WorkspacePayload(
            operation=WorkspaceOperation.ERASE, host_id=host_id, agent_session_id=agent_session_id
        )
        row = OutboxRow(
            id=new_id(),
            created_at=self._clock(),
            org_id=org_id,
            kind=work_row_kind(PlacementWorkKind.WORKSPACE),
            target_id=agent_session_id,
            payload=payload.model_dump(mode="json"),
            actor_id=EMPTY_UUID,
            request_id=new_id(),
            app=AppType.WORKER.value,
        )
        await self._work.enqueue_relayed(org_id, row)
        OUTCOMES.labels(subsystem="exec_relay", outcome="erase_asked").inc()

    async def workspace_work(self, ctx: TenantContext, item_id: UUID) -> WorkItem:
        ctx.require(Permission.READ)
        row = await self._work.get_item(ctx, item_id)
        if row.kind != PlacementWorkKind.WORKSPACE:
            raise NotFound(f"workspace item {item_id} does not exist")
        return row

    async def snapshotted(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, answer: SnapshotAnswer
    ) -> None:
        ctx = await self._service(rctx, host.org_id)
        row = await self._workspace_held(ctx, host, item_id, (WorkspaceOperation.SNAPSHOT,))
        payload = WorkspacePayload.model_validate(row.payload)
        assert payload.agent_session_id is not None and payload.snapshot is not None  # its own rule
        refused = answer.refused
        if refused is None and self._kept is None:
            refused = "this deployment records no snapshot a host keeps"
        if refused is not None:
            log.info("host %s kept no snapshot: %s", host.host_id, refused)
            await self._work.fail_for_good(ctx, row, refused)
            OUTCOMES.labels(subsystem="exec_relay", outcome="snapshot_refused").inc()
            return
        assert self._kept is not None
        kept = HostSnapshot(
            id=payload.snapshot.id,
            reference=answer.reference,
            digest=answer.digest,
            size=answer.size,
        )
        # Recorded before its row is done: the run that waits for it reads
        # the record once the row says it is kept.
        await self._kept(ctx, payload.agent_session_id, kept, host.pool_id, host.host_id)
        try:
            await self._work.complete(ctx, row)
        except LeaseLost, NotFound:
            log.info("workspace item %s: its row was no longer held when it was answered", row.id)
        OUTCOMES.labels(subsystem="exec_relay", outcome="snapshotted").inc()

    async def prepared(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, answer: PrepareAnswer
    ) -> AgentWorkspaceBinding | None:
        ctx = await self._service(rctx, host.org_id)
        row, payload = await self._prepare_held(ctx, host, item_id)
        assert payload.agent_session_id is not None  # `_prepare_held` holds it
        agent_session_id = payload.agent_session_id
        owner = payload.instance_of or agent_session_id
        if (
            answer.refused is not None
            and answer.lost
            and payload.snapshot is not None
            and not await self._kept_elsewhere(ctx, owner, payload, host)
        ):
            # What it was to start from is gone from the store that kept it,
            # or no live host keeps it: no other host is asked, and the run
            # that waits loses it.
            log.warning("host %s lost a snapshot it kept: %s", host.host_id, answer.refused)
            await self._work.fail_for_good(ctx, row, answer.refused)
            OUTCOMES.labels(subsystem="exec_relay", outcome="restore_lost").inc()
            return None
        if answer.refused is not None and answer.unbuilt:
            # Its base failed to build there, as when a setup command
            # failed: an attempt is spent, the reason is kept for the run
            # that waits, and a host builds again after a longer wait.
            log.info("host %s did not build a workspace's base: %s", host.host_id, answer.refused)
            await self._work.fail(ctx, row, answer.refused)
            OUTCOMES.labels(subsystem="exec_relay", outcome="base_unbuilt").inc()
            return None
        if answer.refused is not None:
            # Back to the pool's lane after a wait, for a host that can give
            # it; the loop waits on the resource meanwhile.
            log.info("host %s refused to prepare a workspace: %s", host.host_id, answer.refused)
            await self._work.defer(ctx, row, self._options.prepare_retry)
            OUTCOMES.labels(subsystem="exec_relay", outcome="prepare_refused").inc()
            return None
        assert answer.location is not None  # the answer's own rule
        binding = await self._storage.read_binding(host.org_id, agent_session_id)
        if (
            # A restore replaced the workspace whole: the host that made it
            # holds it, so no run is told of a restore another host's lacks.
            payload.snapshot is not None
            or binding is None
            or binding.host_id == host.host_id
            or not await self._holds(ctx, owner, binding.host_id)
        ):
            binding = await self._bind(
                ctx, agent_session_id, host.host_id, answer.location, payload.instance_of
            )
        try:
            await self._work.complete(ctx, row)
        except LeaseLost, NotFound:
            log.info("workspace item %s: its row was no longer held when it was answered", row.id)
        OUTCOMES.labels(subsystem="exec_relay", outcome="prepared").inc()
        return binding

    async def released(self, rctx: RequestContext, host: HostIdentity, item_id: UUID) -> None:
        ctx = await self._service(rctx, host.org_id)
        row = await self._workspace_held(
            ctx,
            host,
            item_id,
            (WorkspaceOperation.RELEASE, WorkspaceOperation.PURGE, WorkspaceOperation.ERASE),
        )
        try:
            await self._work.complete(ctx, row)
        except LeaseLost, NotFound:
            log.info("workspace item %s: its row was no longer held when it was answered", row.id)
        OUTCOMES.labels(subsystem="exec_relay", outcome="released").inc()

    # The runner's side.

    async def send(
        self,
        rctx: RequestContext,
        org_id: UUID,
        call: ExecCall,
        occurrence: int,
        content: bytes | None = None,
    ) -> ExecItem:
        if (content is not None) != isinstance(call.request, WriteRequest):
            raise ValidationFailed("a write carries its content, and no other operation does")
        ctx = await self._service(rctx, org_id)
        await self._admit(ctx, call.agent_session_id, call.epoch)
        request = REQUESTS.dump_json(call.request)
        item_id = exec_id(call.key, request, occurrence)
        stored = await self._storage.read_item(org_id, item_id)
        if stored is not None:
            return await self._attach(ctx, stored, call, content)
        binding = await self._storage.read_binding(org_id, call.agent_session_id)
        if binding is None:
            raise NoWorkspaceHost(
                f"session {call.agent_session_id} is pinned to its tenant's hosts, and no host "
                "holds its workspace yet; its calls never run on the platform's VMs"
            )
        if not await self._holds(
            ctx, binding.instance_of or call.agent_session_id, binding.host_id
        ):
            # A revoked host never claims again: a command queued on its lane
            # would wait for good. The run prepares again on the pool.
            raise NoWorkspaceHost(
                f"the host that held session {call.agent_session_id}'s workspace is no longer a live "
                "host of its pool; its workspace is made again before its calls run"
            )
        contents = await self._contents(
            ctx, call.agent_session_id, item_id, 1, call.request, content
        )
        sealed = await self._seal.seal(
            ctx, call.agent_session_id, call.key, contents.model_dump_json().encode()
        )
        if sealed is None:
            await self._abort(org_id, contents)
            raise ContentNotKept(
                f"session {call.agent_session_id} keeps no content at rest, so its commands "
                "are not relayed into its tenant's wall"
            )
        now = self._clock()
        item = ExecItem(
            id=item_id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            agent_session_id=call.agent_session_id,
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
            await self._abort(org_id, contents)
            met = await self._storage.read_item(org_id, item_id)
            if met is None:
                raise NotFound(f"exec item {item_id} not found")
            return await self._attach(ctx, met, call, content)
        if content is not None:
            # Put once the item is made and before it is queued, so no host
            # is handed a write whose object is not there.
            try:
                await self._put(ctx, contents, content)
            except Exception:
                outcome = ExecOutcome(refused="object_not_kept", refused_status=503)
                await self._settle(ctx, item, outcome)
                raise
        await self._enqueue(ctx, item, call.by_person, binding.instance_of or item.agent_session_id)
        OUTCOMES.labels(subsystem="exec_relay", outcome="sent").inc()
        return item

    async def take(self, rctx: RequestContext, org_id: UUID, item_id: UUID) -> bytes:
        ctx = await self._service(rctx, org_id)
        item = await self._item(org_id, item_id)
        contents = await self._contents_of(ctx, item)
        result = await self._result_of(ctx, item)
        if (
            item.state is not ExecState.DONE
            or contents.file_out is None
            or result is None
            or result.file is None
        ):
            raise NotFound(f"exec item {item_id} holds no file to take")
        slot, stored = contents.file_out, result.file
        try:
            sealed = await self._buckets.get(org_id, BUCKET, slot.reference, deadline=ctx.deadline)
        except BlobNotFound:
            raise NotFound(f"the file of exec item {item_id} was taken") from None
        try:
            return await asyncio.to_thread(
                open_object, _key(slot.key), slot.reference, stored.size, stored.digest, sealed
            )
        finally:
            await self._delete(org_id, slot.reference)

    async def watch(
        self, rctx: RequestContext, org_id: UUID, item_id: UUID, after_seq: int
    ) -> ExecProgress:
        ctx = await self._service(rctx, org_id)
        item = await self._item(org_id, item_id)
        texts: list[PartText] = []
        held = await self._streams.read(item.id, {item.row_id: after_seq}, self._options.output)
        for entry in (
            entry for run in held if run.stream == item.row_id for _, entry in run.entries
        ):
            opened = await self._seal.open(ctx, item.agent_session_id, item.key, entry)
            # Once the session's key is gone, so is the text it sealed.
            if opened is not None:
                texts.extend(part for part in PARTS.validate_json(opened) if part.seq > after_seq)
        output = None
        if item.state is ExecState.DONE:
            # A reader whose next part the stream let go reads the output
            # whole, never its tail alone.
            if texts and texts[0].seq != after_seq + 1:
                texts = []
            output = await self._output_of(ctx, item)
        return ExecProgress(
            state=item.state, parts=tuple(texts), outcome=item.outcome, output=output
        )

    async def stop(
        self, rctx: RequestContext, org_id: UUID, item_id: UUID, kind: StopKind, epoch: int | None
    ) -> ExecItem:
        ctx = await self._service(rctx, org_id)
        item = await self._item(org_id, item_id)
        await self._admit(ctx, item.agent_session_id, epoch)
        if item.state is ExecState.QUEUED:
            # No host took it: it never runs. Its row ends with it, unless a
            # host claimed the row first: the claim that finds the item
            # settled completes it.
            stopped = await self._settle(ctx, item, ExecOutcome(stopped=kind))
            if stopped is not None:
                await self._end_row(ctx, stopped)
            return stopped or await self._item(org_id, item_id)
        if item.state is ExecState.RUNNING:
            await self._control(ctx, item, kind)
        return item

    async def running(
        self, rctx: RequestContext, org_id: UUID, agent_session_id: UUID
    ) -> list[ExecItem]:
        await self._service(rctx, org_id)
        return await self._storage.read_running(org_id, agent_session_id, self._options.call_items)

    async def interrupt_running(
        self, rctx: RequestContext, org_id: UUID, agent_session_id: UUID, below: int | None
    ) -> list[ExecItem]:
        ctx = await self._service(rctx, org_id)
        running = await self._storage.read_running(
            org_id, agent_session_id, self._options.call_items
        )
        answered: list[ExecItem] = []
        for item in running:
            if below is not None and not stale(item.epoch, below):
                continue
            outcome = ExecOutcome(stopped=StopKind.INTERRUPT)
            ended = await self._settle(ctx, item, outcome, revoke=True)
            if ended is not None:
                answered.append(ended)
                OUTCOMES.labels(subsystem="exec_relay", outcome="interrupted").inc()
        return answered

    async def outcome_of(
        self, rctx: RequestContext, org_id: UUID, agent_session_id: UUID, key: UUID, epoch: int
    ) -> ExecItem | None:
        ctx = await self._service(rctx, org_id)
        await self._admit(ctx, agent_session_id, epoch)
        commands = [
            item
            for item in await self._storage.read_items_by_key(
                org_id, agent_session_id, key, self._options.call_items
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
            OUTCOMES.labels(subsystem="exec_relay", outcome="unsafe_reclaimed").inc()
            return False
        cursor = await self._steps.get_cursor(ctx, item.agent_session_id)
        if stale(item.epoch, cursor.epoch):
            outcome = ExecOutcome(refused=StaleExec.code, refused_status=StaleExec.http_status)
            await self._settle(ctx, item, outcome)
            await self._work.fail_for_good(ctx, row, "a command of a run that lost its session")
            OUTCOMES.labels(subsystem="exec_relay", outcome="stale").inc()
            return False
        request, last, fresh = item.request, None, None
        if row.attempts > 1:
            # An earlier claim may have sent parts of this one's uploads: a
            # host uploads only what its own claim sealed, so each starts
            # anew, and what the earlier one sent goes.
            request, last, fresh = await self._fresh_uploads(ctx, item)
        now = self._clock()
        started = _copy(
            item,
            now,
            state=ExecState.RUNNING,
            claim=row.model_dump(mode="json"),
            lease_expires_at=row.lease_expires_at,
            request=request,
        )
        if await self._storage.write_item(ctx.org_id, started, item.version) is None:
            # A stop or the sweep moved it meanwhile; the next claim decides.
            if fresh is not None:
                await self._abort_uploads(ctx.org_id, fresh)
            await self._work.release(ctx, row)
            return False
        if last is not None:
            await self._abort_uploads(ctx.org_id, last)
        return True

    async def detail(self, rctx: RequestContext, host: HostIdentity, item_id: UUID) -> ExecDetail:
        ctx = await self._service(rctx, host.org_id)
        item = await self._held(host, item_id)
        contents = await self._contents_of(ctx, item)
        url = expires_at = None
        if contents.file_in is not None:
            ttl = self._options.object_ttl
            expires_at = self._clock() + ttl
            url = await self._buckets.presign_get(
                host.org_id, BUCKET, contents.file_in.reference, ttl
            )
        return ExecDetail(
            item_id=item.id,
            key=item.key,
            org_id=host.org_id,
            agent_session_id=item.agent_session_id,
            effect=item.effect,
            deadline=item.deadline,
            epoch=item.epoch,
            spec=item.spec,
            location=item.location,
            request=contents.request,
            output=contents.output,
            file_in=contents.file_in,
            file_out=contents.file_out,
            url=url,
            url_expires_at=expires_at,
        )

    async def issue_upload(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, kind: ObjectKind, size: int
    ) -> IssuedObjectUpload:
        ctx = await self._service(rctx, host.org_id)
        item = await self._held(host, item_id)
        contents = await self._contents_of(ctx, item)
        slot, most = _uploaded(contents, kind)
        if slot is None:
            raise ValidationFailed(f"exec item {item_id} uploads no {kind}")
        if not 0 <= size <= most:
            raise ValidationFailed(f"the {kind} of exec item {item_id} is 0 to {most} bytes")
        plan = sealed_parts(size)
        held = await self._buckets.list_parts(
            host.org_id, BUCKET, slot.reference, slot.upload_id, len(plan), deadline=ctx.deadline
        )
        have = {part.number: part.size_bytes for part in held}
        missing = [part for part in plan if have.get(part.number) != part.size_bytes]
        ttl = self._options.object_ttl
        expires_at = self._clock() + ttl
        parts = [
            IssuedObjectPart(
                number=part.number,
                offset=part.offset,
                size_bytes=part.size_bytes,
                url=await self._buckets.presign_part(
                    host.org_id,
                    BUCKET,
                    slot.reference,
                    slot.upload_id,
                    part.number,
                    part.size_bytes,
                    ttl,
                ),
            )
            for part in missing[: self._options.parts_per_issue]
        ]
        return IssuedObjectUpload(parts=tuple(parts), remaining=len(missing), expires_at=expires_at)

    async def push_parts(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, parts: Sequence[SentPart]
    ) -> None:
        if not 0 < len(parts) <= PUSH_PARTS or sum(len(p.data) for p in parts) > PUSH_BYTES:
            raise ValidationFailed(
                f"a push is one to {PUSH_PARTS} parts, of {PUSH_BYTES} bytes at most"
            )
        texts: list[PartText] = []
        for part in parts:
            # The bytes are checked against their hash before anything reads them.
            text = _decoded(_crossed(CrossingKind.STREAM_PART, part.crossing, part.data))
            if part.stream not in STREAMS:
                raise ValidationFailed(f"no stream {part.stream!r}; a part is stdout or stderr")
            if not (texts[-1].seq if texts else -1) < part.seq < self._options.max_parts:
                raise ValidationFailed(
                    f"a push's parts are in their order, each one of {self._options.max_parts}"
                )
            stream = "stdout" if part.stream == "stdout" else "stderr"
            texts.append(PartText(seq=part.seq, stream=stream, text=text))
        ctx = await self._service(rctx, host.org_id)
        item = await self._held(host, item_id)
        sealed = await self._seal.seal(
            ctx, item.agent_session_id, item.key, PARTS.dump_json(tuple(texts))
        )
        if sealed is None:
            return  # the session keeps no content at rest now: nothing is kept
        # One entry, numbered by its last part, so a push sent again lands
        # nothing, and a reader resumes after the last part it read.
        await self._streams.append(
            item.id, item.row_id, [(texts[-1].seq, sealed)], self._options.output
        )

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
        try:
            contents: ItemContent | None = await self._contents_of(ctx, item)
        except NotFound:
            contents = None  # its key went: what it printed or read is noise
        if contents is None:
            result = result.model_copy(update={"output": None, "file": None})
        else:
            result = await self._landed(ctx, contents, result)
        kept = ResultContent.model_validate(result.model_dump(exclude={"outcome"}))
        sealed = await self._seal.seal(
            ctx, item.agent_session_id, item.key, kept.model_dump_json().encode()
        )
        token = claimed_row(item).claim_token
        while True:
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
            if written is not None:
                break
            # A renewal of this same claim, still landing as the host ends
            # the item, moves its version and settles nothing: the result
            # lands on the version it left. Any other write settled the item
            # or handed it to another claim, and the result lands nothing.
            moved = await self._storage.read_item(host.org_id, item_id)
            if (
                moved is None
                or not held_by(moved, worker_of(host))
                or claimed_row(moved).claim_token != token
            ):
                raise ItemNotHeld(f"exec item {item_id} was settled before its result arrived")
            item = moved
        if contents is None:
            await self._delete_under(
                host.org_id, dispatch_objects(item.agent_session_id, item.id, item.dispatch)
            )
        else:
            await self._kept_objects(host.org_id, contents, result)
        try:
            await self._work.complete(ctx, claimed_row(item))
        except LeaseLost, NotFound:
            # The result is the record; a row its lease left is the queue's
            # to settle, and a claim of it finds the item done.
            log.info("exec item %s: its row was no longer held when its result landed", item.id)
        OUTCOMES.labels(subsystem="exec_relay", outcome="done").inc()
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
                OUTCOMES.labels(subsystem="exec_relay", outcome="requeued").inc()
            else:
                if await self._settle(ctx, item, ExecOutcome(), revoke=True) is None:
                    continue
                OUTCOMES.labels(subsystem="exec_relay", outcome="interrupted").inc()
            settled += 1
        return settled

    async def bindings(self, after: UUID | None) -> list[tuple[UUID, AgentWorkspaceBinding]]:
        return await self._storage.read_bindings(after, self._options.sweep_batch)

    async def end_host(self, rctx: RequestContext, org_id: UUID, host_id: UUID) -> int:
        ctx = await self._service(rctx, org_id)
        ended = await self._work.end_open_on_lane(
            org_id, host_lane(host_id), "its host was revoked"
        )
        settled = 0
        for row in ended:
            if row.kind != PlacementWorkKind.EXEC:
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
                OUTCOMES.labels(subsystem="exec_relay", outcome="interrupted").inc()
        return settled

    async def purge_agent_session(self, org_id: UUID, agent_session_id: UUID) -> None:
        # Its commands' queue rows end first: a row whose item is gone would
        # wait for good on the lane of a host that never claims again.
        await self._work.end_open_for_target(
            org_id, PlacementWorkKind.EXEC, agent_session_id, "its session was purged"
        )
        # Its objects go before its items, so none outlives the record of it.
        await self._delete_under(org_id, session_objects(agent_session_id), purged=True)
        while await self._storage.purge_agent_session(
            org_id, agent_session_id, self._options.purge_batch
        ):
            pass

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        await self._delete_under(ctx.org_id, OBJECTS, purged=True)
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
        to the agent project of the session it is for."""
        # Where on the host it is made is the host's to choose, so a prepare
        # reads no path of the host's. One that may build its base first
        # asks for what the base's setup reaches.
        isolation, egress, _ = asks(spec, "")
        if setup_reaches(spec):
            egress = None
        agent_project = await self._agent_projects.agent_project_of(ctx, instance_of or target)
        payload = WorkspacePayload(
            operation=WorkspaceOperation.PREPARE,
            pool_id=pool_id,
            agent_session_id=target,
            spec=spec,
            isolation=isolation,
            egress=egress,
            agent_project_id=None if agent_project is None else agent_project.id,
            instance_of=instance_of,
        )
        await self._enqueue_workspace(ctx, target, payload)

    async def _enqueue_workspace(
        self, ctx: TenantContext, target: UUID, payload: WorkspacePayload
    ) -> UUID:
        """`workspace` work for the workspace under `target`, on the lane its
        payload names; its id."""
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
                kind=PlacementWorkKind.WORKSPACE,
                target_id=target,
                idempotency_key=row,
                request_id=ctx.request_id,
                traceparent=ctx.traceparent,
                payload=payload.model_dump(mode="json"),
                status=WorkStatus.QUEUED,
                available_at=now,
            ),
        )
        return row

    async def _service(self, rctx: RequestContext, org_id: UUID) -> TenantContext:
        """The tenant's service context: the exec relay runs below any principal,
        for the runner's transport and for a host, which is no person."""
        return await self._tenancy.service_context(rctx, org_id, EMPTY_UUID)

    async def _admit(self, ctx: TenantContext, agent_session_id: UUID, epoch: int | None) -> None:
        """Refuses a run that no longer holds the session: nothing it sends,
        stops, or asks after acts."""
        if epoch is None:
            return
        cursor = await self._steps.get_cursor(ctx, agent_session_id)
        if stale(epoch, cursor.epoch):
            OUTCOMES.labels(subsystem="exec_relay", outcome="stale").inc()
            raise StaleExec(
                f"epoch {epoch} is below session {agent_session_id}'s {cursor.epoch}: "
                "the run that sent it no longer holds the session"
            )

    async def _asked_of(self, ctx: TenantContext, agent_session_id: UUID, pool_id: UUID) -> bool:
        """Whether the session's prepare waits or runs on `pool_id`'s lane. One
        that waits on another pool's, as the session moved since, is ended,
        so no host of a pool it left makes it. One a host of that pool holds
        already is left to end: its host is no host of the session's pool,
        so the session never runs there. A release that waits is ended too:
        a prepare is asked only when no live host holds the workspace, so
        none is left for it to let go. A snapshot or an erase is a host's
        store's, and is left to run."""
        latest = await self._work.latest_for_target(
            ctx, PlacementWorkKind.WORKSPACE, agent_session_id
        )
        if latest is None or latest.status not in OPEN:
            return False
        try:
            waiting = WorkspacePayload.model_validate(latest.payload)
        except ValidationError:
            waiting = None
        if waiting is not None and waiting.operation in (
            WorkspaceOperation.SNAPSHOT,
            WorkspaceOperation.ERASE,
        ):
            return False
        asked_of = None if waiting is None else waiting.pool_id
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
        if payload.pool_id != host.pool_id or payload.agent_session_id is None:
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
            and row.kind == PlacementWorkKind.WORKSPACE
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

    async def _kept_elsewhere(
        self, ctx: TenantContext, owner: UUID, payload: WorkspacePayload, host: HostIdentity
    ) -> bool:
        """Whether a restore this host could not make may still be made by
        another: it waits on the pool's lane, and the host that kept its
        snapshot is another live host of the pool, which, or a host that
        shares its store, may. On the lane of the host that holds the
        workspace, no other host is asked."""
        kept_by = None if payload.snapshot is None else payload.snapshot.kept_by
        return (
            payload.host_id is None
            and kept_by is not None
            and kept_by != host.host_id
            and await self._holds(ctx, owner, kept_by)
        )

    async def _holds(self, ctx: TenantContext, agent_session_id: UUID, host_id: UUID) -> bool:
        """Whether the host is a live host of the session's pool: one that was
        neither revoked nor moved holds what it prepared, for the session or
        for an instance made for it."""
        placed = await self._hosts.work_placement(ctx, agent_session_id)
        if placed.pool is None:
            return False
        status = await self._hosts.get_host(ctx, placed.pool.id, host_id)
        return status is not None and status.host.revoked_at is None

    async def _attach(
        self, ctx: TenantContext, item: ExecItem, call: ExecCall, content: bytes | None
    ) -> ExecItem:
        """The item a call that sent it before meets: as it stands, so the
        run attaches to its execution or reads its result; or put on the
        queue again, when a repeat cannot harm it and its last run did not
        end its command. Sent again, it moves objects of its own dispatch,
        and what its last one moved goes."""
        if item.agent_session_id != call.agent_session_id:
            raise ValidationFailed(f"exec item {item.id} is another session's")
        now = self._clock()
        if resent(item):
            dispatch = item.dispatch + 1
            try:
                last: ItemContent | None = await self._contents_of(ctx, item)
            except NotFound:
                last = None
            contents = await self._contents(
                ctx, item.agent_session_id, item.id, dispatch, call.request, content
            )
            sealed = await self._seal.seal(
                ctx, item.agent_session_id, item.key, contents.model_dump_json().encode()
            )
            if sealed is None:
                await self._abort(ctx.org_id, contents)
                raise ContentNotKept(
                    f"session {item.agent_session_id} keeps no content at rest, so its commands "
                    "are not relayed into its tenant's wall"
                )
            again = _copy(
                item,
                now,
                state=ExecState.QUEUED,
                dispatch=dispatch,
                row_id=row_id(item.id, dispatch),
                epoch=call.epoch,
                deadline=call.deadline,
                request=sealed,
                claim=None,
                lease_expires_at=None,
                outcome=None,
                output=None,
                result_sha256=None,
                settled_at=None,
            )
            written = await self._storage.write_item(ctx.org_id, again, item.version)
            if written is None:
                await self._abort(ctx.org_id, contents)
                raise PreconditionFailed(f"exec item {item.id} moved while it was sent again")
            if last is not None:
                await self._abort(ctx.org_id, last)
            await self._delete_under(
                ctx.org_id, dispatch_objects(item.agent_session_id, item.id, item.dispatch)
            )
            if content is not None:
                await self._put(ctx, contents, content)
            binding = await self._storage.read_binding(ctx.org_id, item.agent_session_id)
            owner = (
                item.agent_session_id
                if binding is None
                else binding.instance_of or item.agent_session_id
            )
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
        agent project of `owner`, the session the workspace is or was made for,
        which a host's owner may hold its work to, and whether a person sent
        it by hand, which the owner may refuse."""
        isolation, egress, reads = asks(item.spec, item.location)
        agent_project = await self._agent_projects.agent_project_of(ctx, owner)
        payload = ExecPayload(
            host_id=item.host_id,
            item_id=item.id,
            agent_session_id=item.agent_session_id,
            key=item.key,
            operation=item.operation,
            effect=item.effect,
            spec=item.spec,
            isolation=isolation,
            egress=egress,
            reads=reads,
            by_person=by_person,
            agent_project_id=None if agent_project is None else agent_project.id,
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
                kind=PlacementWorkKind.EXEC,
                target_id=item.agent_session_id,
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
        if written is not None:
            await self._let_go_of(ctx, written)
        return written

    async def _end_row(self, ctx: TenantContext, item: ExecItem) -> None:
        """Ends the queue row of an item that never ran, while it is queued:
        a host that is gone never claims it to find the item settled."""
        try:
            row = await self._work.get_item(ctx, item.row_id)
        except NotFound:
            return
        await self._work.end_queued(ctx, row, "its command was stopped before a host took it")

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
            agent_session_id=item.agent_session_id,
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

    # The objects an item moves.

    async def _contents(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        item_id: UUID,
        dispatch: int,
        request: ExecRequest,
        content: bytes | None,
    ) -> ItemContent:
        """What an item seals on its `dispatch`th time on the queue: its
        operation, and each object it moves under a key of its own. A
        write's names its file, put once the item is made; an object its
        host uploads has its upload started here."""

        async def slot(kind: ObjectKind) -> ObjectSlot:
            reference = object_reference(agent_session_id, item_id, dispatch, kind)
            upload_id = await self._buckets.start_upload(
                ctx.org_id, BUCKET, reference, OCTETS, deadline=ctx.deadline
            )
            return ObjectSlot(reference=reference, key=_b64(new_key()), upload_id=upload_id)

        if isinstance(request, WriteRequest):
            if content is None:
                raise ValidationFailed("a write carries its content")
            named = ObjectRef(
                reference=object_reference(agent_session_id, item_id, dispatch, "file"),
                size=len(content),
                digest=await asyncio.to_thread(digest_of, content),
                key=_b64(new_key()),
            )
            return ItemContent(request=request, file_in=named)
        if isinstance(request, ReadRequest):
            return ItemContent(request=request, file_out=await slot("file"))
        return ItemContent(request=request, output=await slot("output"))

    async def _put(self, ctx: TenantContext, contents: ItemContent, content: bytes) -> None:
        """A write's file, sealed under its object's key: the platform's own
        write, a `put`."""
        named = contents.file_in
        assert named is not None  # a write's contents name its file
        sealed = await asyncio.to_thread(seal_object, _key(named.key), named.reference, content)
        await self._buckets.put(
            ctx.org_id, BUCKET, named.reference, sealed, OCTETS, deadline=ctx.deadline
        )

    async def _contents_of(self, ctx: TenantContext, item: ExecItem) -> ItemContent:
        opened = await self._seal.open(ctx, item.agent_session_id, item.key, item.request)
        if opened is None:
            raise NotFound(f"exec item {item.id}: its session's content is gone")
        return ItemContent.model_validate_json(opened)

    async def _result_of(self, ctx: TenantContext, item: ExecItem) -> ResultContent | None:
        """What the item's result says, opened; None before it has one, and
        once its key is gone."""
        if item.output is None:
            return None
        opened = await self._seal.open(ctx, item.agent_session_id, item.key, item.output)
        return None if opened is None else ResultContent.model_validate_json(opened)

    async def _output_of(self, ctx: TenantContext, item: ExecItem) -> ExecOutput:
        """A done item's output as the runner reads it: its output object
        read from the store and opened, once it matches what its host
        declared, with the rest of its result. Empty once its key is gone."""
        result = await self._result_of(ctx, item)
        if result is None:
            return ExecOutput()
        printed = Printed()
        detail = result.detail
        if result.output is not None:
            try:
                slot = (await self._contents_of(ctx, item)).output
                if slot is not None:
                    printed = await self._printed(ctx, slot, result.output)
            except NotFound:
                pass  # its key went since: so did what it printed
            except ObjectRefused as error:
                log.warning("exec item %s: %s", item.id, error.message)
                detail = detail or "its output did not open to what its host declared of it"
        return ExecOutput(
            stdout=printed.stdout,
            stderr=printed.stderr,
            entries=printed.entries,
            file=result.file,
            offset=result.offset,
            detail=detail,
        )

    async def _printed(self, ctx: TenantContext, slot: ObjectSlot, stored: StoredObject) -> Printed:
        try:
            sealed = await self._buckets.get(
                ctx.org_id, BUCKET, slot.reference, deadline=ctx.deadline
            )
        except BlobNotFound:
            raise NotFound(f"no output at {slot.reference}") from None
        opened = await asyncio.to_thread(
            open_object, _key(slot.key), slot.reference, stored.size, stored.digest, sealed
        )
        return Printed.model_validate_json(opened)

    async def _landed(
        self, ctx: TenantContext, contents: ItemContent, result: ExecResult
    ) -> ExecResult:
        """The result once each object it names is whole in the store: its
        upload completed to the plan of the size its host declared, within
        its bound, before the result lands, so whoever reads the item done
        finds its objects. An output that is not whole is not kept, and the
        result says so; a read whose file is not whole is refused. A result
        that then lands nothing leaves what it completed to the item's next
        claim, whose uploads are its own (`_fresh_uploads`)."""
        output_slot, most = _uploaded(contents, "output")
        if output_slot is None and result.output is not None:
            raise ValidationFailed("an item that prints nothing uploads no output")
        if output_slot is not None and result.output is not None:
            if not await self._completed(ctx, output_slot, result.output, most):
                detail = "its output was not kept whole in the store"
                result = result.model_copy(update={"output": None, "detail": detail})
        file_slot, most = _uploaded(contents, "file")
        if file_slot is None and result.file is not None:
            raise ValidationFailed("an item that reads nothing uploads no file")
        if file_slot is not None and result.outcome.refused is None:
            if result.file is None or not await self._completed(ctx, file_slot, result.file, most):
                refused = ExecOutcome(refused=ObjectRefused.code, refused_status=422)
                detail = "the file it read was not kept whole in the store"
                result = result.model_copy(
                    update={"outcome": refused, "file": None, "detail": detail}
                )
        if result.outcome.refused is not None:
            result = result.model_copy(update={"file": None})
        return result

    async def _completed(
        self, ctx: TenantContext, slot: ObjectSlot, stored: StoredObject, most: int
    ) -> bool:
        """Whether the object its host declared is whole in the store now:
        within its bound, and its upload completed to the plan of its size."""
        if stored.size > most:
            return False
        try:
            await self._buckets.complete_upload(
                ctx.org_id,
                BUCKET,
                slot.reference,
                slot.upload_id,
                sealed_size(stored.size),
                deadline=ctx.deadline,
            )
        except (UploadRefused, UploadNotFound) as error:
            log.warning("%s: %s", slot.reference, error.message)
            return False
        return True

    async def _kept_objects(self, org_id: UUID, contents: ItemContent, result: ExecResult) -> None:
        """Once a result lands: each upload it names nothing of let go, and
        a write's file removed, since it settled."""
        for slot, stored in ((contents.output, result.output), (contents.file_out, result.file)):
            if slot is not None and stored is None:
                await self._let_go(org_id, slot)
        if contents.file_in is not None:
            await self._delete(org_id, contents.file_in.reference)

    async def _fresh_uploads(
        self, ctx: TenantContext, item: ExecItem
    ) -> tuple[bytes, ItemContent | None, ItemContent | None]:
        """The item's sealed contents with a new upload of each object its
        host uploads, the contents it had, and the new ones; as it stands
        when it uploads nothing, or its key went."""
        try:
            last = await self._contents_of(ctx, item)
        except NotFound:
            return item.request, None, None
        if last.output is None and last.file_out is None:
            return item.request, None, None

        async def again(slot: ObjectSlot | None) -> ObjectSlot | None:
            if slot is None:
                return None
            upload_id = await self._buckets.start_upload(
                ctx.org_id, BUCKET, slot.reference, OCTETS, deadline=ctx.deadline
            )
            return slot.model_copy(update={"upload_id": upload_id})

        fresh = last.model_copy(
            update={"output": await again(last.output), "file_out": await again(last.file_out)}
        )
        sealed = await self._seal.seal(
            ctx, item.agent_session_id, item.key, fresh.model_dump_json().encode()
        )
        if sealed is None:
            await self._abort_uploads(ctx.org_id, fresh)
            return item.request, None, None
        return sealed, last, fresh

    async def _abort_uploads(self, org_id: UUID, contents: ItemContent) -> None:
        """The uploads `contents` names, aborted, with no object removed."""
        for slot in (contents.output, contents.file_out):
            if slot is None:
                continue
            try:
                await self._buckets.abort_upload(org_id, BUCKET, slot.reference, slot.upload_id)
            except InfraException as error:
                log.warning("%s: its upload was not aborted: %s", slot.reference, error.message)

    async def _let_go_of(self, ctx: TenantContext, item: ExecItem) -> None:
        """What an item that ended `interrupted` moved: no result names its
        objects now, so its uploads and its files go."""
        try:
            contents = await self._contents_of(ctx, item)
        except NotFound:
            contents = None  # its key went: what it moved is noise, and goes
        if contents is not None:
            await self._abort(ctx.org_id, contents)
        await self._delete_under(
            ctx.org_id, dispatch_objects(item.agent_session_id, item.id, item.dispatch)
        )

    async def _abort(self, org_id: UUID, contents: ItemContent) -> None:
        """Lets go of every object `contents` names."""
        for slot in (contents.output, contents.file_out):
            if slot is not None:
                await self._let_go(org_id, slot)
        if contents.file_in is not None:
            await self._delete(org_id, contents.file_in.reference)

    async def _let_go(self, org_id: UUID, slot: ObjectSlot) -> None:
        try:
            await self._buckets.abort_upload(org_id, BUCKET, slot.reference, slot.upload_id)
        except InfraException as error:
            # The store's own rule ends an upload a day on.
            log.warning("%s: its upload was not aborted: %s", slot.reference, error.message)
        await self._delete(org_id, slot.reference)

    async def _delete(self, org_id: UUID, reference: str) -> None:
        try:
            await self._buckets.delete(org_id, BUCKET, reference)
        except InfraException as error:
            # Sealed, and the session's purge takes it.
            log.warning("%s: it was not removed: %s", reference, error.message)

    async def _delete_under(self, org_id: UUID, prefix: str, *, purged: bool = False) -> None:
        """Every object under `prefix`, a page at a time. One the store
        fails to list or remove is left, sealed, to the session's purge,
        whose own failure is raised, so the sweep purges it again."""
        batch = self._options.purge_batch
        after: str | None = None
        try:
            while keys := await self._buckets.list(org_id, BUCKET, prefix, batch, after):
                for key in keys:
                    await self._buckets.delete(org_id, BUCKET, key)
                if len(keys) < batch:
                    return
                after = keys[-1]
        except InfraException as error:
            if purged:
                raise
            log.warning("%s: its objects were not all removed: %s", prefix, error.message)


def _b64(key: bytes) -> str:
    return base64.b64encode(key).decode()


def _key(text: str) -> bytes:
    return base64.b64decode(text)


def _uploaded(contents: ItemContent, kind: ObjectKind) -> tuple[ObjectSlot | None, int]:
    """The object of `kind` an item's host uploads, and the most it holds:
    an output within `OUTPUT_BYTES`, a read's file within what it asked."""
    if kind == "output":
        return contents.output, OUTPUT_BYTES
    request = contents.request
    most = request.max_bytes if isinstance(request, ReadRequest) else 0
    return contents.file_out, most


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
