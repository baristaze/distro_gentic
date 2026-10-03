"""The runner's duty to the instances its host holds: one no run accounts
for is let go.

A run that dies mid-loop never releases its workspace, so its instance
would run on for good. Each pass reads what this host's provider holds,
whichever process prepared it. An instance whose session has a loop item
queued or claimed is a run's, or soon will be, and is left alone: a live
run always holds its loop item claimed. One no run accounts for is let go
once a pass finds it so past a grace, which a follow-up still reattaches
within. It goes through the release a run makes, under its tenant's
context: what its checkout holds is pushed to a snapshot ref first, and a
push that does not land lets nothing go, so the next pass tries again.

An instance is purged only on proof that nothing is left to keep its
work for: its tenant's org row marks it deleted. One whose tenant this
database holds no row of, or whose session it holds no history of, is
left alone and logged: after a restore to an earlier point, it may hold
the only copy of its work. A session marked deleted keeps its history
and may come back, so its instance is released like any other.

A session pinned to its tenant's hosts keeps its instance on the host
that prepared it, which no runner holds, and which a loop's end leaves
warm. So each pass also reads every workspace a host holds, by the
relay's bindings, and holds it to the same proofs. One no run accounts
for past the grace is let go the same way, from here: its checkout's work
is pushed to a snapshot ref through the relay, by the platform's git and
with no credential in the workspace, and only then is its host asked,
as `workspace` work on its lane, to let the instance go and keep its
files. Its work is not pushed again when a snapshot taken after the
session's last step holds it already, as a loop's end leaves it. One a
person holds, its loop parked on a hand-over, is theirs and stays. One
whose release was asked since its session's last loop is not asked
again, answered or failed: a failed one is logged, and is asked anew
only after the session's next loop. One whose host is offline, revoked, or out of the
session's pool waits for a pass that reaches it. A deleted tenant's is
left to the tenant's purge: nothing is sent into its wall."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field, ValidationError

from acme.infra.workspaces import HeldInstance, Workspace, WorkspaceProviderInterface
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.base import EMPTY_UUID, Platform, utcnow
from acme.om.context import RequestContext, TenantContext
from acme.om.exceptions import NotFound
from acme.om.placement.types.work import WorkspaceOperation, WorkspacePayload
from acme.om.relay.manager import RelayManagerInterface
from acme.om.relay.types.exec import WorkspaceBinding
from acme.om.steps import StepsManagerInterface
from acme.om.steps.types.header import ParkReason
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.work import WorkManagerInterface
from acme.om.work.types.work_item import WorkKind, WorkStatus
from acme.om.workspaces.manager import WorkspacesManagerInterface
from acme.om.workspaces.rules import snapshot_at

log = logging.getLogger(__name__)


class HeldOptions(Platform):
    # How long an instance no run accounts for stays, counted from the first
    # pass that finds it so, before it is let go.
    grace: timedelta = Field(default=timedelta(minutes=5), gt=timedelta(0))


class HeldWorkspacesSweep:
    """Lets go of each instance this host holds that no run accounts for,
    once a pass finds it so past the grace, and of each such instance a
    tenant's host holds when `relay` is given. When a pass first found each
    one so is held in memory: a runner that restarts counts the grace
    again, so it lets go later, never sooner."""

    def __init__(
        self,
        provider: WorkspaceProviderInterface,
        tools: ToolsManagerInterface,
        workspaces: WorkspacesManagerInterface,
        sessions: AgentSessionsManagerInterface,
        steps: StepsManagerInterface,
        work: WorkManagerInterface,
        tenancy: TenancyManagerInterface,
        options: HeldOptions,
        clock: Callable[[], datetime] = utcnow,
        relay: RelayManagerInterface | None = None,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._workspaces = workspaces
        self._sessions = sessions
        self._steps = steps
        self._work = work
        self._tenancy = tenancy
        self._options = options
        self._clock = clock
        self._relay = relay
        # Each instance no run accounted for at a pass, and when a pass first
        # found it so.
        self._unaccounted: dict[UUID, datetime] = {}
        # Each instance logged as one this database holds no record of.
        self._logged: set[UUID] = set()
        # Each session whose release was logged as failed, and that release.
        self._failed: dict[UUID, UUID] = {}

    async def __call__(self, rctx: RequestContext) -> int:
        """One pass over what this host holds, then over what the tenants'
        hosts hold; returns how many it let go."""
        held = await self._provider.held()
        hosted = await self._hosted()
        now = self._clock()
        ids = {instance.id for instance in held} | {b.session_id for _, b in hosted}
        self._unaccounted = {id_: at for id_, at in self._unaccounted.items() if id_ in ids}
        self._logged &= ids
        self._failed = {id_: item for id_, item in self._failed.items() if id_ in ids}
        let_go = 0
        for instance in held:
            try:
                if await self._let_go(rctx, instance, now):
                    let_go += 1
            except Exception:
                log.exception(
                    "the instance of session %s of org %s waits for the next pass",
                    instance.id,
                    instance.org_id,
                )
        for org_id, binding in hosted:
            try:
                if await self._let_go_hosted(rctx, org_id, binding, now):
                    let_go += 1
            except Exception:
                log.exception(
                    "the instance of session %s of org %s on host %s waits for the next pass",
                    binding.session_id,
                    org_id,
                    binding.host_name,
                )
        return let_go

    async def _hosted(self) -> list[tuple[UUID, WorkspaceBinding]]:
        """Every workspace a tenant's host holds, by its binding, a page at a
        time; none when this sweep reaches no host."""
        if self._relay is None:
            return []
        found: list[tuple[UUID, WorkspaceBinding]] = []
        after: UUID | None = None
        while page := await self._relay.bindings(after):
            found.extend(page)
            after = page[-1][1].id
        return found

    async def _let_go(self, rctx: RequestContext, instance: HeldInstance, now: datetime) -> bool:
        """Lets one instance go when no run accounts for it past the grace;
        False when it stays. A failed push raises, and it stays."""
        deleted = await self._tenancy.tenant_deleted(rctx, instance.org_id)
        if deleted is None:
            self._unknown(instance, "its tenant")
            return False
        ctx: TenantContext | None = None
        if not deleted:
            # The platform lets it go, as no person: the system user.
            ctx = await self._tenancy.service_context(rctx, instance.org_id, EMPTY_UUID)
            if await self._work.has_open(ctx, WorkKind.LOOP, instance.id):
                self._unaccounted.pop(instance.id, None)
                return False
        since = self._unaccounted.setdefault(instance.id, now)
        if now - since < self._options.grace:
            return False
        if ctx is None:
            await self._tools.purge_workspace(instance.org_id, instance.id)
            log.info(
                "session %s of org %s: its tenant is deleted, and its instance is purged",
                instance.id,
                instance.org_id,
            )
        elif (await self._steps.get_cursor(ctx, instance.id)).epoch == 0:
            # A run took an epoch before it prepared this instance, so a
            # session with none here is one this database has no history of.
            self._unknown(instance, "its session")
            return False
        else:
            pinned = await self._workspaces.get_workspace(ctx, instance.id)
            workspace = Workspace(
                id=instance.id,
                org_id=instance.org_id,
                spec=pinned.spec(),
                location=instance.location,
            )
            await self._tools.release_workspace(ctx, workspace)
            log.info(
                "session %s of org %s: its instance no run held is released",
                instance.id,
                instance.org_id,
            )
        self._unaccounted.pop(instance.id, None)
        return True

    async def _let_go_hosted(
        self, rctx: RequestContext, org_id: UUID, binding: WorkspaceBinding, now: datetime
    ) -> bool:
        """Asks the host that holds one session's workspace to let its
        instance go when no run accounts for it past the grace, once its
        work is pushed; False when it stays. A failed push raises, and it
        stays."""
        assert self._relay is not None
        session_id = binding.session_id
        deleted = await self._tenancy.tenant_deleted(rctx, org_id)
        if deleted is None:
            self._unknown(
                HeldInstance(id=session_id, org_id=org_id, location=binding.location), "its tenant"
            )
            return False
        if deleted:
            self._unaccounted.pop(session_id, None)
            return False
        ctx = await self._tenancy.service_context(rctx, org_id, EMPTY_UUID)
        if (
            await self._work.has_open(ctx, WorkKind.LOOP, session_id)
            or await self._released(ctx, session_id)
            or await self._handed_over(ctx, session_id)
        ):
            self._unaccounted.pop(session_id, None)
            return False
        since = self._unaccounted.setdefault(session_id, now)
        if now - since < self._options.grace:
            return False
        cursor = await self._steps.get_cursor(ctx, session_id)
        if cursor.epoch == 0:
            self._unknown(
                HeldInstance(id=session_id, org_id=org_id, location=binding.location),
                "its session",
            )
            return False
        holder = await self._relay.holder(ctx, session_id)
        if holder is None:
            # Nothing reaches its host now, the snapshot included: a later
            # pass finds it online.
            return False
        pinned = await self._workspaces.get_workspace(ctx, session_id)
        workspace = Workspace(
            id=session_id, org_id=org_id, spec=pinned.spec(), location=holder.location
        )
        if not await self._kept(ctx, session_id, cursor.head, pinned.snapshot_ref):
            # Kept first, through the relay: a push that does not land
            # raises, and the instance and its work stay.
            await self._workspaces.detach(ctx, workspace, cursor.epoch)
        await self._relay.ask_release(ctx, session_id, workspace.spec)
        log.info(
            "session %s of org %s: host %s is asked to let go of its instance no run held",
            session_id,
            org_id,
            holder.host_name,
        )
        self._unaccounted.pop(session_id, None)
        return True

    async def _released(self, ctx: TenantContext, session_id: UUID) -> bool:
        """Whether a release of the session's instance was asked after its
        last loop moved, answered or failed: nothing has run on it since,
        and a host that fails it would fail it again. A failed one is
        logged, once a process."""
        asked = await self._work.latest_for_target(ctx, WorkKind.WORKSPACE, session_id)
        if asked is None:
            return False
        try:
            operation = WorkspacePayload.model_validate(asked.payload).operation
        except ValidationError:
            return False
        if operation is not WorkspaceOperation.RELEASE:
            return False
        loop = await self._work.latest_for_target(ctx, WorkKind.LOOP, session_id)
        if loop is not None and loop.updated_at > asked.created_at:
            return False
        if asked.status is WorkStatus.FAILED and self._failed.get(session_id) != asked.id:
            self._failed[session_id] = asked.id
            log.warning(
                "session %s of org %s: its host did not let its instance go (%s); "
                "it is asked again after the session's next loop",
                session_id,
                ctx.org_id,
                asked.last_error,
            )
        return True

    async def _handed_over(self, ctx: TenantContext, session_id: UUID) -> bool:
        """Whether a person holds the session's workspace: its loop is parked
        on a hand-over, which only their giving back clears, and their
        commands run in it meanwhile."""
        try:
            session = await self._sessions.get_session(ctx, session_id)
        except NotFound:
            # One marked deleted is let go like any other.
            return False
        return session.park is not None and session.park.reason is ParkReason.HANDOVER

    async def _kept(
        self, ctx: TenantContext, session_id: UUID, head: int, snapshot_ref: str | None
    ) -> bool:
        """Whether the session's last snapshot was taken after its last step,
        as a loop's end takes it: no call has run in its checkout since, so a
        push would only keep the same work again."""
        taken = None if snapshot_ref is None else snapshot_at(snapshot_ref)
        if taken is None:
            return False
        if head == 0:
            return True
        page = await self._steps.get_steps(ctx, session_id, head - 1, 1)
        return all(step.created_at <= taken for step in page.items)

    def _unknown(self, instance: HeldInstance, what: str) -> None:
        """Logs, once a process, an instance this database cannot account
        for, which stays."""
        if instance.id in self._logged:
            return
        self._logged.add(instance.id)
        log.warning(
            "session %s of org %s: this database holds no record of %s, so its "
            "instance at %s is left as it is",
            instance.id,
            instance.org_id,
            what,
            instance.location,
        )
