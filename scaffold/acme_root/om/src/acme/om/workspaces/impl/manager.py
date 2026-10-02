import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import Field, ValidationError

from acme.infra.workspaces import IsolationMode, IsolationSpec, Workspace, WorkspaceLost
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents.types.kind import AgentKindCatalog
from acme.om.base import Platform, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.evidence.types.validation import Delivery
from acme.om.exceptions import (
    NotFound,
    PreconditionFailed,
    Unavailable,
    UniqueKeyTaken,
    UnknownAgentKind,
    ValidationFailed,
)
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, versioned_row
from acme.om.tenancy import TenancyManagerInterface
from acme.om.workspaces import rules
from acme.om.workspaces.git import RepositoryReaderInterface, WorkspaceGitInterface
from acme.om.workspaces.manager import WorkspacesManagerInterface
from acme.om.workspaces.projects import PullRequestsInterface, WorkspaceProjectsInterface
from acme.om.workspaces.storage import WorkspaceStorageInterface
from acme.om.workspaces.types.egress import EgressAllowlist, EgressDecision, EgressRequest
from acme.om.workspaces.types.source import BranchPlan, RepositoryBinding, RepositoryWrite
from acme.om.workspaces.types.workspace import SessionWorkspace

log = logging.getLogger(__name__)

CREATED = "workspaces.egress_allowlist.created"
UPDATED = "workspaces.egress_allowlist.updated"


class WorkspacesOptions(Platform):
    # The platform's internal network, which no workspace reaches: every
    # private range unless a deployment names its own.
    internal_networks: tuple[str, ...] = rules.PLATFORM_NETWORKS
    # The networks the stations sit on, which no workspace reaches either.
    station_networks: tuple[str, ...] = ()
    purge_batch: int = Field(default=1000, gt=0)  # rows one purge statement deletes at most
    # How often a write of the cache's state is tried against a writer that
    # landed first.
    write_tries: int = Field(default=3, ge=1)


class WorkspacesManagerImpl(WorkspacesManagerInterface):
    def __init__(
        self,
        storage: WorkspaceStorageInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        kinds: AgentKindCatalog,
        projects: WorkspaceProjectsInterface,
        pull_requests: PullRequestsInterface,
        git: WorkspaceGitInterface,
        reader: RepositoryReaderInterface,
        options: WorkspacesOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._relay = relay
        self._kinds = kinds
        self._projects = projects
        self._pull_requests = pull_requests
        self._git = git
        self._reader = reader
        self._options = options
        self._clock = clock
        self._internal = rules.networks(options.internal_networks) + rules.networks(
            options.station_networks
        )

    # The pin.

    async def pin(self, ctx: TenantContext, session: AgentSession) -> SessionWorkspace | None:
        ctx.require(Permission.WRITE)
        stored = await self._storage.read_workspace(ctx.org_id, session.id)
        if stored is not None:
            return stored
        try:
            kind = self._kinds.get(session.kind, session.kind_version)
        except UnknownAgentKind:
            log.warning(
                "session %s of org %s is of kind %s at version %d, which this process "
                "does not declare: nothing is pinned",
                session.id,
                ctx.org_id,
                session.kind,
                session.kind_version,
            )
            return None
        project_id = await self._projects.project_of(ctx, session)
        allowlist = (
            None
            if project_id is None
            else await self._storage.read_allowlist(ctx.org_id, project_id)
        )
        label = f"{kind.name} at version {kind.version}"
        return await self._land(ctx, session.id, kind.isolation, label, project_id, allowlist)

    async def get_workspace(self, ctx: TenantContext, session_id: UUID) -> SessionWorkspace:
        ctx.require(Permission.READ)
        stored = await self._storage.read_workspace(ctx.org_id, session_id)
        if stored is None:
            raise NotFound(f"the workspace of session {session_id} was never pinned")
        return stored

    async def pinned(
        self, ctx: TenantContext, session_id: UUID, asked: IsolationSpec
    ) -> IsolationSpec:
        ctx.require(Permission.WRITE)
        stored = await self._storage.read_workspace(ctx.org_id, session_id)
        if stored is not None:
            return stored.spec()
        if asked.mode is IsolationMode.NONE:
            return asked
        # Created before pins, or by a process that does not declare its
        # kind: pinned now, to what its loop asks, its kind's at the version
        # it runs, and held to that from here on.
        log.warning(
            "session %s of org %s had no pinned isolation: it is pinned at its first prepare",
            session_id,
            ctx.org_id,
        )
        landed = await self._land(ctx, session_id, asked, "its first loop's kind", None, None)
        return landed.spec()

    # Around a loop.

    async def attach(self, ctx: TenantContext, workspace: Workspace) -> Workspace:
        ctx.require(Permission.WRITE)
        held = await self._storage.read_workspace(ctx.org_id, workspace.id)
        if held is None:
            return workspace
        told = [] if held.notice is None else [held.notice]
        seen = held.branch_seen
        kept: str | None = None
        binding = await self._binding(ctx, held)
        if binding is not None:
            state = await self._git.sync(ctx, workspace, binding, held.branch)
            fate = None
            if not state.remote and seen:
                fate = await self._pull_requests.fate_of(ctx, binding, held.branch)
            plan = rules.branch_plan(state, seen=seen, fate=fate)
            if plan in (BranchPlan.LOST, BranchPlan.DIVERGED):
                why = (
                    "is gone from its repository, and nothing says why"
                    if plan is BranchPlan.LOST
                    else "moved here and on its repository both, and nothing merges them"
                )
                log.error(
                    "session %s of org %s: its branch %s %s",
                    workspace.id,
                    ctx.org_id,
                    held.branch,
                    why,
                )
                raise WorkspaceLost(f"the branch {held.branch} of session {workspace.id} {why}")
            if plan in (BranchPlan.CUT, BranchPlan.REBUILD):
                # What the checkout holds is kept before it is cut over: a
                # push that does not land raises, and nothing is cut.
                ref = rules.snapshot_ref(held.branch, self._clock())
                snapshot = await self._git.snapshot(ctx, workspace, binding, held.branch, ref)
                if snapshot.commit is not None:
                    kept = snapshot.ref
                    told.append(rules.told_of_snapshot(snapshot.ref, snapshot.commit))
                await self._git.cut(ctx, workspace, binding, held.branch)
            if plan is BranchPlan.REBUILD and fate is not None:
                told.append(rules.told_of_rebuild(held.branch, fate, binding.default_branch))
                log.warning(
                    "session %s of org %s: its branch %s was rebuilt after its pull request %s",
                    workspace.id,
                    ctx.org_id,
                    held.branch,
                    fate.value,
                )
            seen = state.remote
        if held.notice is not None or seen != held.branch_seen or kept is not None:
            await self._update(ctx, workspace.id, notice=None, branch_seen=seen, snapshot_ref=kept)
        return workspace.model_copy(update={"changed": "\n\n".join(told) or None})

    async def detach(self, ctx: TenantContext, workspace: Workspace) -> None:
        ctx.require(Permission.WRITE)
        held = await self._storage.read_workspace(ctx.org_id, workspace.id)
        if held is None:
            return
        binding = await self._binding(ctx, held)
        if binding is None:
            return
        ref = rules.snapshot_ref(held.branch, self._clock())
        snapshot = await self._git.snapshot(ctx, workspace, binding, held.branch, ref)
        seen = held.branch_seen or snapshot.remote_branch
        if snapshot.commit is None:
            if seen != held.branch_seen:
                await self._update(ctx, workspace.id, notice=held.notice, branch_seen=seen)
            return
        log.info(
            "session %s of org %s: the work its loop left is %s on %s",
            workspace.id,
            ctx.org_id,
            snapshot.commit,
            snapshot.ref,
        )
        notice = rules.told_of_snapshot(snapshot.ref, snapshot.commit)
        await self._update(
            ctx, workspace.id, notice=notice, branch_seen=seen, snapshot_ref=snapshot.ref
        )

    async def delivery(self, ctx: TenantContext, workspace: Workspace) -> Delivery:
        ctx.require(Permission.READ)
        held = await self._storage.read_workspace(ctx.org_id, workspace.id)
        binding = None if held is None else await self._binding(ctx, held)
        if held is None or binding is None:
            raise Unavailable(f"session {workspace.id} works on no bound repository")
        # What was delivered is read from the repository, outside the
        # workspace; the checkout tells only what was not: work uncommitted,
        # or committed and not pushed.
        delivered = await self._reader.delivered(binding, held.branch)
        local = await self._git.checkout(ctx, workspace)
        try:
            return Delivery(
                project=rules.project_key(binding),
                base=delivered.base,
                head=delivered.head,
                dirty=local.dirty or local.head != delivered.head,
                changed=delivered.changed,
            )
        except ValidationError as error:
            raise Unavailable(
                f"the work product of session {workspace.id}: {error}"[:300]
            ) from None

    # Egress, and what acts outward.

    async def get_allowlist(self, ctx: TenantContext, project_id: UUID) -> EgressAllowlist | None:
        ctx.require(Permission.READ)
        return await self._storage.read_allowlist(ctx.org_id, project_id)

    async def write_allowlist(
        self, ctx: TenantContext, allowlist: EgressAllowlist
    ) -> EgressAllowlist:
        ctx.require(Permission.MANAGE_MEMBERS)
        stored = await self._storage.read_allowlist(ctx.org_id, allowlist.project_id)
        now = self._clock()
        terms = {"rules": allowlist.rules, "open": allowlist.open, "reason": allowlist.reason}
        if stored is None:
            created = EgressAllowlist.model_validate(
                {
                    **allowlist.model_dump(),
                    "created_at": now,
                    "updated_at": now,
                    "created_by": ctx.user_id,
                    "updated_by": ctx.user_id,
                    "version": 1,
                }
            )
            rows = (versioned_row(ctx, CREATED, created.id, created.version),)
            try:
                landed = await self._storage.create_allowlist(ctx.org_id, created, rows)
            except UniqueKeyTaken as error:
                raise PreconditionFailed(
                    f"the allowlist of project {allowlist.project_id} was written meanwhile"
                ) from error
            if not landed:
                raise PreconditionFailed(f"egress allowlist {created.id} is written already")
            await self._relay_all(ctx, rows)
            self._recorded(ctx, created)
            return created
        if allowlist.version != stored.version:
            raise PreconditionFailed(f"egress allowlist {stored.id} is at version {stored.version}")
        # The copy starts from the stored row: its id and provenance stay.
        updated = EgressAllowlist.model_validate(
            {
                **stored.model_dump(),
                **terms,
                "version": stored.version + 1,
                "updated_at": now,
                "updated_by": ctx.user_id,
            }
        )
        rows = (versioned_row(ctx, UPDATED, updated.id, updated.version),)
        await self._storage.write_allowlist(ctx.org_id, updated, stored.version, rows)
        await self._relay_all(ctx, rows)
        self._recorded(ctx, updated)
        return updated

    async def egress(
        self, ctx: TenantContext, session_id: UUID, request: EgressRequest
    ) -> EgressDecision:
        ctx.require(Permission.READ)
        held = await self._storage.read_workspace(ctx.org_id, session_id)
        if held is None:
            return EgressDecision(allowed=False, reason="this session never pinned its egress")
        return rules.egress_decision(held.egress, held.rules, request, self._internal)

    async def outward(self, ctx: TenantContext, session_id: UUID, write: RepositoryWrite) -> bool:
        ctx.require(Permission.READ)
        held = await self._storage.read_workspace(ctx.org_id, session_id)
        if held is None:
            return True
        binding = await self._binding(ctx, held)
        return not rules.is_work_product(write, binding, held.branch)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    # Helpers.

    async def _land(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spec: IsolationSpec,
        label: str,
        project_id: UUID | None,
        allowlist: EgressAllowlist | None,
    ) -> SessionWorkspace:
        """Writes the pin, once: one landed first is answered as it is."""
        now = self._clock()
        try:
            egress, egress_rules, source = rules.pinned_egress(spec.egress, label, allowlist)
            workspace = SessionWorkspace(
                id=session_id,
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                project_id=project_id,
                level=spec.mode,
                limits=spec.limits,
                egress=egress,
                rules=egress_rules,
                egress_source=source,
                branch=rules.session_branch(session_id),
            )
        except ValidationError as error:
            raise ValidationFailed(
                f"the workspace of session {session_id}: {error}"[:500]
            ) from None
        if not await self._storage.create_workspace(ctx.org_id, workspace):
            landed = await self._storage.read_workspace(ctx.org_id, session_id)
            if landed is None:
                raise PreconditionFailed(f"the workspace of session {session_id} is another's")
            return landed
        log.info(
            "session %s of org %s pinned %s isolation, egress %s: %s",
            session_id,
            ctx.org_id,
            workspace.level.value,
            workspace.egress.value,
            source,
        )
        return workspace

    async def _binding(
        self, ctx: TenantContext, held: SessionWorkspace
    ) -> RepositoryBinding | None:
        if held.project_id is None:
            return None
        return await self._projects.binding_of(ctx, held.project_id)

    async def _update(
        self,
        ctx: TenantContext,
        session_id: UUID,
        *,
        notice: str | None,
        branch_seen: bool,
        snapshot_ref: str | None = None,
    ) -> None:
        """The cache's state, written over the stored row and read again when
        a writer landed first."""
        for attempt in range(self._options.write_tries):
            stored = await self._storage.read_workspace(ctx.org_id, session_id)
            if stored is None:
                return
            changes: dict[str, object] = {
                "notice": notice,
                "branch_seen": branch_seen,
                "version": stored.version + 1,
                "updated_at": self._clock(),
                "updated_by": ctx.user_id,
            }
            if snapshot_ref is not None:
                changes["snapshot_ref"] = snapshot_ref
            try:
                await self._storage.write_workspace(
                    ctx.org_id, stored.model_copy(update=changes), stored.version
                )
                return
            except PreconditionFailed:
                if attempt + 1 == self._options.write_tries:
                    raise

    def _recorded(self, ctx: TenantContext, allowlist: EgressAllowlist) -> None:
        if allowlist.open:
            log.warning(
                "user %s of org %s opened the egress of project %s: %s",
                ctx.user_id,
                ctx.org_id,
                allowlist.project_id,
                allowlist.reason,
            )

    async def _relay_all(self, ctx: TenantContext, rows: tuple[OutboxRow, ...]) -> None:
        """The write has committed; a relay that fails is left to the sweep."""
        if rows:
            await self._relay.relay_all(ctx.org_id, rows)
