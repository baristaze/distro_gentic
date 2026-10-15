"""The runner's duty to the instances its host holds: one no run accounts
for is let go.

A run that dies mid-loop never releases its workspace, so its instance
would run on for good. Each pass reads what this host's provider holds,
whichever process prepared it. An instance whose session has a loop item
queued or claimed is a run's, or soon will be, and is left alone: a live
run always holds its loop item claimed. One no run accounts for is let go
once a pass finds it so past its grace, which a follow-up still reattaches
within: the warm grace of its session's kind, read once when a pass first
finds it so, and never past the prompt cache's life. One whose session
this database no longer reads takes the default grace. It goes through the release a run makes, under its tenant's
context: what its checkout holds is pushed to a snapshot ref first, and a
push that does not land lets nothing go, so the next pass tries again.

A session kept by snapshots whose instance no snapshot holds keeps it: a
call or a change since its latest snapshot, or a run whose snapshot was
refused, left state its files alone do not hold, which a release would
lose. It is logged once a head, and its next run prepares it as it
stands, so that run's end snapshots it.

An instance is purged only on proof that nothing is left to keep its
work for: its tenant's org row marks it deleted. One whose tenant this
database holds no row of, or whose session it holds no history of, is
left alone and logged: after a restore to an earlier point, it may hold
the only copy of its work. A session marked deleted keeps its history
and may come back, so its instance is released like any other.

A session pinned to its tenant's hosts keeps its instance on the host
that prepared it, which no runner holds, and which a loop's end leaves
warm. So each pass also reads every workspace a host holds, by the
exec relay's bindings, and holds it to the same proofs. One no run accounts
for past the grace is let go the same way, from here: its checkout's work
is pushed to a snapshot ref through the exec relay, by the platform's git and
with no credential in the workspace, and only then is its host asked,
as `workspace` work on its lane, to let the instance go and keep its
files. Its work is not pushed again when a snapshot taken after the
session's last step holds it already, as a loop's end leaves it. One a
person holds, its loop parked on a hand-over, is theirs and stays. One
whose release was asked since its session's last loop is not asked
again, answered or failed: a failed one is logged, and is asked anew
only after the session's next loop. A snapshot push the forge refuses,
here or through a host, is final for the session's head: it is logged,
the instance stays, and its push is tried again only once the session's
next loop has moved its head. One whose host is offline, revoked, or out of the
session's pool waits for a pass that reaches it. A deleted tenant's is
left to the tenant's purge: nothing is sent into its wall."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import ValidationError

from acme.infra.agent_workspaces import (
    AgentWorkspaceProviderInterface,
    Durability,
    HeldInstance,
    AgentWorkspace,
)
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agent_steps.types.header import ParkReason
from acme.om.agent_workspaces.manager import AgentWorkspacesManagerInterface
from acme.om.agent_workspaces.rules import snapshot_at
from acme.om.agents.loop_rules import kept_snapshot
from acme.om.base import EMPTY_UUID, utcnow
from acme.om.cloud_pool import CloudPoolManagerInterface
from acme.om.context import RequestContext, TenantContext
from acme.om.exceptions import NotAuthorized, NotFound, ValidationFailed
from acme.om.exec_relay.manager import ExecRelayManagerInterface
from acme.om.exec_relay.types.exec import AgentWorkspaceBinding
from acme.om.placement.types.work import WorkspaceOperation, WorkspacePayload
from acme.om.platform_agents.kinds import WARM_GRACE
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.work import WorkManagerInterface
from acme.om.work.types.work_item import WorkKind, WorkStatus

log = logging.getLogger(__name__)

HISTORY_PAGE = 500
"""How many steps a read of a session's history takes at a time."""

REFUSED = (ValidationFailed, NotAuthorized)
"""A push the forge refuses for good, as a repository no installation of
the tenant's holds: pushing the same work again would be refused again."""


Graces = Callable[[str], timedelta]
"""Each agent kind's warm grace, by its name (`ProductKinds.warm_grace`)."""


class HeldWorkspacesSweep:
    """Lets go of each instance this host holds that no run accounts for,
    once a pass finds it so past its session's kind's grace (`graces`), and
    of each such instance a tenant's host holds when `exec_relay` is given, or a
    machine of the cloud pool holds when `cloud` is. When each one may go,
    counted from the pass that first found it so, is held in memory: a
    runner that restarts counts the grace again, so it lets go later, never
    sooner."""

    def __init__(
        self,
        provider: AgentWorkspaceProviderInterface,
        tools: ToolsManagerInterface,
        agent_workspaces: AgentWorkspacesManagerInterface,
        sessions: AgentSessionsManagerInterface,
        steps: AgentStepsManagerInterface,
        work: WorkManagerInterface,
        tenancy: TenancyManagerInterface,
        graces: Graces,
        clock: Callable[[], datetime] = utcnow,
        exec_relay: ExecRelayManagerInterface | None = None,
        cloud: CloudPoolManagerInterface | None = None,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._agent_workspaces = agent_workspaces
        self._sessions = sessions
        self._steps = steps
        self._work = work
        self._tenancy = tenancy
        self._graces = graces
        self._clock = clock
        self._exec_relay = exec_relay
        self._cloud = cloud
        # Each instance no run accounted for at a pass, and when it may go:
        # its grace past the pass that first found it so.
        self._unaccounted: dict[UUID, datetime] = {}
        # Each instance logged as one this database holds no record of.
        self._logged: set[UUID] = set()
        # Each session whose release was logged as failed, and that release.
        self._failed: dict[UUID, UUID] = {}
        # Each session whose snapshot push was refused, and its head then.
        self._refused: dict[UUID, int] = {}
        # Each session kept by snapshots whose instance no snapshot held, and
        # its head then.
        self._unkept: dict[UUID, int] = {}

    async def __call__(self, rctx: RequestContext) -> int:
        """One pass over what this host holds, then over what the tenants'
        hosts hold; returns how many it let go."""
        held = await self._provider.held_instances()
        hosted = await self._hosted()
        now = self._clock()
        ids = {instance.id for instance in held} | {b.agent_session_id for _, b in hosted}
        self._unaccounted = {id_: at for id_, at in self._unaccounted.items() if id_ in ids}
        self._logged &= ids
        self._failed = {id_: item for id_, item in self._failed.items() if id_ in ids}
        self._refused = {id_: head for id_, head in self._refused.items() if id_ in ids}
        self._unkept = {id_: head for id_, head in self._unkept.items() if id_ in ids}
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
                    binding.agent_session_id,
                    org_id,
                    binding.host_name,
                )
        return let_go

    async def _hosted(self) -> list[tuple[UUID, AgentWorkspaceBinding]]:
        """Every workspace a tenant's host holds, by its binding, a page at a
        time; none when this sweep reaches no host."""
        if self._exec_relay is None:
            return []
        found: list[tuple[UUID, AgentWorkspaceBinding]] = []
        after: UUID | None = None
        while page := await self._exec_relay.bindings(after):
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
        if now < await self._until(ctx, instance.id, now):
            return False
        if ctx is None:
            await self._tools.purge_agent_workspace(instance.org_id, instance.id)
            log.info(
                "session %s of org %s: its tenant is deleted, and its instance is purged",
                instance.id,
                instance.org_id,
            )
        elif (cursor := await self._steps.get_cursor(ctx, instance.id)).epoch == 0:
            # A run took an epoch before it prepared this instance, so a
            # session with none here is one this database has no history of.
            self._unknown(instance, "its session")
            return False
        elif cursor.head in (self._refused.get(instance.id), self._unkept.get(instance.id)):
            return False
        else:
            pinned = await self._agent_workspaces.get_workspace(ctx, instance.id)
            if await self._unsnapshotted(ctx, instance.id, pinned.durability, cursor.head):
                return False
            workspace = AgentWorkspace(
                id=instance.id,
                org_id=instance.org_id,
                spec=pinned.spec(),
                location=instance.location,
            )
            try:
                await self._tools.release_agent_workspace(ctx, workspace)
            except REFUSED as refused:
                self._refuse(ctx, instance.id, cursor.head, refused)
                return False
            log.info(
                "session %s of org %s: its instance no run held is released",
                instance.id,
                instance.org_id,
            )
        self._unaccounted.pop(instance.id, None)
        return True

    async def _let_go_hosted(
        self, rctx: RequestContext, org_id: UUID, binding: AgentWorkspaceBinding, now: datetime
    ) -> bool:
        """Asks the host that holds one session's workspace to let its
        instance go when no run accounts for it past the grace, once its
        work is pushed; False when it stays. A failed push raises, and it
        stays."""
        assert self._exec_relay is not None
        agent_session_id = binding.agent_session_id
        deleted = await self._tenancy.tenant_deleted(rctx, org_id)
        if deleted is None:
            self._unknown(
                HeldInstance(id=agent_session_id, org_id=org_id, location=binding.location),
                "its tenant",
            )
            return False
        if deleted:
            self._unaccounted.pop(agent_session_id, None)
            return False
        ctx = await self._tenancy.service_context(rctx, org_id, EMPTY_UUID)
        if (
            await self._work.has_open(ctx, WorkKind.LOOP, agent_session_id)
            or await self._released(ctx, agent_session_id)
            or await self._handed_over(ctx, agent_session_id)
        ):
            self._unaccounted.pop(agent_session_id, None)
            return False
        if now < await self._until(ctx, agent_session_id, now):
            return False
        cursor = await self._steps.get_cursor(ctx, agent_session_id)
        if cursor.epoch == 0:
            self._unknown(
                HeldInstance(id=agent_session_id, org_id=org_id, location=binding.location),
                "its session",
            )
            return False
        if cursor.head in (self._refused.get(agent_session_id), self._unkept.get(agent_session_id)):
            return False
        holder = await self._exec_relay.holder(ctx, agent_session_id)
        if holder is None:
            # Nothing reaches its host now, the snapshot included: a later
            # pass finds it online.
            return False
        pinned = await self._agent_workspaces.get_workspace(ctx, agent_session_id)
        if await self._unsnapshotted(ctx, agent_session_id, pinned.durability, cursor.head):
            return False
        workspace = AgentWorkspace(
            id=agent_session_id, org_id=org_id, spec=pinned.spec(), location=holder.location
        )
        if not await self._kept(ctx, agent_session_id, cursor.head, pinned.snapshot_ref):
            # Kept first, through the exec relay: a push that does not land
            # raises, and the instance and its work stay.
            try:
                await self._agent_workspaces.detach(ctx, workspace, cursor.epoch)
            except REFUSED as refused:
                self._refuse(ctx, agent_session_id, cursor.head, refused)
                return False
        if self._cloud is not None and await self._cloud.holds(ctx, agent_session_id):
            # A machine of the cloud pool is the instance: it goes, its disk
            # with it, and the session's next loop starts another.
            await self._cloud.release(ctx, agent_session_id)
        else:
            await self._exec_relay.ask_release(ctx, agent_session_id, workspace.spec)
        log.info(
            "session %s of org %s: host %s is asked to let go of its instance no run held",
            agent_session_id,
            org_id,
            holder.host_name,
        )
        self._unaccounted.pop(agent_session_id, None)
        return True

    async def _until(
        self, ctx: TenantContext | None, agent_session_id: UUID, now: datetime
    ) -> datetime:
        """When the instance of a session no run accounts for may go: its
        grace past the pass that first found it so, read at that pass."""
        until = self._unaccounted.get(agent_session_id)
        if until is None:
            until = self._unaccounted[agent_session_id] = now + await self._grace(
                ctx, agent_session_id
            )
        return until

    async def _grace(self, ctx: TenantContext | None, agent_session_id: UUID) -> timedelta:
        """The warm grace of the session's kind, or the default for a session
        of a deleted tenant, or one marked deleted."""
        if ctx is None:
            return WARM_GRACE
        try:
            session = await self._sessions.get_agent_session(ctx, agent_session_id)
        except NotFound:
            return WARM_GRACE
        return self._graces(session.kind)

    async def _released(self, ctx: TenantContext, agent_session_id: UUID) -> bool:
        """Whether a release of the session's instance was asked after its
        last loop moved, answered or failed: nothing has run on it since,
        and a host that fails it would fail it again. A failed one is
        logged, once a process."""
        asked = await self._work.latest_for_target(ctx, WorkKind.WORKSPACE, agent_session_id)
        if asked is None:
            return False
        try:
            operation = WorkspacePayload.model_validate(asked.payload).operation
        except ValidationError:
            return False
        if operation is not WorkspaceOperation.RELEASE:
            return False
        loop = await self._work.latest_for_target(ctx, WorkKind.LOOP, agent_session_id)
        if loop is not None and loop.updated_at > asked.created_at:
            return False
        if asked.status is WorkStatus.FAILED and self._failed.get(agent_session_id) != asked.id:
            self._failed[agent_session_id] = asked.id
            log.warning(
                "session %s of org %s: its host did not let its instance go (%s); "
                "it is asked again after the session's next loop",
                agent_session_id,
                ctx.org_id,
                asked.last_error,
            )
        return True

    async def _handed_over(self, ctx: TenantContext, agent_session_id: UUID) -> bool:
        """Whether a person holds the session's workspace: its loop is parked
        on a hand-over, which only their giving back clears, and their
        commands run in it meanwhile."""
        try:
            session = await self._sessions.get_agent_session(ctx, agent_session_id)
        except NotFound:
            # One marked deleted is let go like any other.
            return False
        return session.park is not None and session.park.reason is ParkReason.HANDOVER

    async def _kept(
        self, ctx: TenantContext, agent_session_id: UUID, head: int, snapshot_ref: str | None
    ) -> bool:
        """Whether the session's last snapshot was taken after its last step,
        as a loop's end takes it: no call has run in its checkout since, so a
        push would only keep the same work again."""
        taken = None if snapshot_ref is None else snapshot_at(snapshot_ref)
        if taken is None:
            return False
        if head == 0:
            return True
        page = await self._steps.get_agent_steps(ctx, agent_session_id, head - 1, 1)
        return all(step.created_at <= taken for step in page.items)

    async def _unsnapshotted(
        self, ctx: TenantContext, agent_session_id: UUID, durability: Durability, head: int
    ) -> bool:
        """Whether the session keeps its workspace by snapshots and no snapshot
        holds its instance as it stands: one is recorded, and logged, at the
        session's head, so no pass reads its history again until a loop
        moves it."""
        if durability is not Durability.SNAPSHOT:
            return False
        if kept_snapshot(await self._history(ctx, agent_session_id)) is not None:
            return False
        self._unkept[agent_session_id] = head
        log.warning(
            "session %s of org %s: no snapshot holds its workspace's instance, which stays "
            "until a run's end snapshots it",
            agent_session_id,
            ctx.org_id,
        )
        return True

    async def _history(self, ctx: TenantContext, agent_session_id: UUID) -> list[AgentStep]:
        steps: list[AgentStep] = []
        after = 0
        while True:
            page = await self._steps.get_agent_steps(ctx, agent_session_id, after, HISTORY_PAGE)
            steps.extend(page.items)
            if not page.has_more or not page.items:
                return steps
            after = page.items[-1].seq

    def _refuse(
        self, ctx: TenantContext, agent_session_id: UUID, head: int, refused: Exception
    ) -> None:
        """Records a snapshot push the forge refused at the session's head,
        and logs it: the instance and its work stay, and no pass pushes
        again until the session's next loop moves its head."""
        self._refused[agent_session_id] = head
        log.warning(
            "session %s of org %s: its snapshot push was refused (%s); its instance "
            "stays, and it is pushed again after the session's next loop",
            agent_session_id,
            ctx.org_id,
            refused,
        )

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
