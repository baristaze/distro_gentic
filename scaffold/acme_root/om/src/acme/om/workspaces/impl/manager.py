import json
import logging
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field, SecretStr, ValidationError

from acme.infra.exceptions import InfraException
from acme.infra.secrets import SecretsInterface
from acme.infra.workspaces import IsolationMode, IsolationSpec, Workspace, WorkspaceLost
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents.types.kind import AgentKindCatalog
from acme.om.base import Platform, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.evidence.types.validation import Delivery
from acme.om.exceptions import (
    NotAuthorized,
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
from acme.om.tenancy.rules import hash_token
from acme.om.workspaces import rules
from acme.om.workspaces.git import RepositoryReaderInterface, WorkspaceGitInterface
from acme.om.workspaces.impl.tools import HeldWorkspaces
from acme.om.workspaces.manager import WorkspacesManagerInterface
from acme.om.workspaces.projects import (
    PullRequestsInterface,
    SourceControlInterface,
    WorkspaceProjectsInterface,
)
from acme.om.workspaces.storage import WorkspaceStorageInterface
from acme.om.workspaces.types.credential import FetchCredential, PushToken, RepositoryCredential
from acme.om.workspaces.types.egress import EgressAllowlist, EgressDecision, EgressRequest
from acme.om.workspaces.types.source import (
    BranchPlan,
    OpenedPullRequest,
    RepositoryBinding,
    RepositoryWrite,
    WriteKind,
)
from acme.om.workspaces.types.workspace import SessionWorkspace

log = logging.getLogger(__name__)

CREATED = "workspaces.egress_allowlist.created"
UPDATED = "workspaces.egress_allowlist.updated"
SECRET_NOT_FOUND = "secret_not_found"
"""The code the tenant's store answers for a name it holds no value under."""


class WorkspacesOptions(Platform):
    # The platform's internal network, which no workspace reaches: every
    # private range unless a deployment names its own.
    internal_networks: tuple[str, ...] = rules.PLATFORM_NETWORKS
    purge_batch: int = Field(default=1000, gt=0)  # rows one purge statement deletes at most
    # How often a write of the cache's state is tried against a writer that
    # landed first.
    write_tries: int = Field(default=3, ge=1)
    # The longest a push token lives; a prepare or a release of the loop's
    # workspace ends it sooner.
    push_token_lifetime: timedelta = Field(default=timedelta(minutes=15), gt=timedelta(0))


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
        secrets_store: SecretsInterface,
        source_control: SourceControlInterface,
        held: HeldWorkspaces,
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
        self._secrets = secrets_store
        self._source_control = source_control
        self._held = held
        self._clock = clock
        self._internal = rules.networks(options.internal_networks)

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

    async def attach(self, ctx: TenantContext, workspace: Workspace, epoch: int) -> Workspace:
        ctx.require(Permission.WRITE)
        held = await self._storage.read_workspace(ctx.org_id, workspace.id)
        if held is None:
            return workspace
        told = list(held.notices)
        seen = held.branch_seen
        kept: str | None = None
        forget = False
        binding = await self._binding(ctx, held)
        if binding is not None:
            # The platform reads the repository on its own host, with the
            # project's fetch credential, and the checkout takes a bundle:
            # no credential enters the workspace.
            # A branch the repository never held may live on in its last
            # snapshot alone, which the cut then starts from. A loop not yet
            # told of the snapshot is told to restore its work from there,
            # so it comes in then too, whatever the branch.
            last = held.snapshot_ref if not seen or held.notices else None
            incoming = await self._reader.incoming(
                binding,
                held.branch,
                await self._fetch_credential(ctx, binding.project_id),
                snapshot=last,
            )
            state = await self._git.sync(
                ctx, workspace, binding, held.branch, incoming, epoch=epoch
            )
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
                at = self._clock()
                ref = rules.snapshot_ref(held.branch, at)
                snapshot = await self._git.snapshot(
                    ctx, workspace, binding, held.branch, ref, epoch=epoch
                )
                if snapshot.commit is not None:
                    kept = snapshot.ref
                    told.append(rules.told_of_snapshot(snapshot.ref, snapshot.commit, at))
                if plan is BranchPlan.REBUILD:
                    # Its work is in its pull request: a later cut starts
                    # from the default branch, never from a snapshot of it.
                    kept, forget = None, True
                start = last if plan is BranchPlan.CUT else None
                await self._git.cut(ctx, workspace, binding, held.branch, epoch=epoch, start=start)
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
        changed = bool(held.notices) or seen != held.branch_seen or kept is not None or forget
        if changed or held.push_digest is not None:
            await self._update(
                ctx,
                workspace.id,
                branch_seen=seen,
                snapshot_ref=kept,
                forget_snapshot=forget,
                told=held.notices,
            )
        return workspace.model_copy(update={"changed": "\n\n".join(told) or None})

    async def detach(self, ctx: TenantContext, workspace: Workspace, epoch: int) -> None:
        ctx.require(Permission.WRITE)
        held = await self._storage.read_workspace(ctx.org_id, workspace.id)
        if held is None:
            return
        binding = await self._binding(ctx, held)
        if binding is None:
            return
        at = self._clock()
        ref = rules.snapshot_ref(held.branch, at)
        snapshot = await self._git.snapshot(ctx, workspace, binding, held.branch, ref, epoch=epoch)
        seen = held.branch_seen or snapshot.remote_branch
        if snapshot.commit is None:
            if seen != held.branch_seen or held.push_digest is not None:
                await self._update(ctx, workspace.id, branch_seen=seen)
            return
        log.info(
            "session %s of org %s: the work its loop left is %s on %s",
            workspace.id,
            ctx.org_id,
            snapshot.commit,
            snapshot.ref,
        )
        await self._update(
            ctx,
            workspace.id,
            branch_seen=seen,
            snapshot_ref=snapshot.ref,
            adds=rules.told_of_snapshot(snapshot.ref, snapshot.commit, at),
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
        local = await self._git.checkout(ctx, workspace, epoch=self._epoch(workspace.id))
        delivered = await self._reader.delivered(
            binding,
            held.branch,
            await self._fetch_credential(ctx, binding.project_id),
            cut=local.base,
        )
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

    async def checks_tree(
        self,
        ctx: TenantContext,
        project_id: UUID,
        version: str,
        source: str,
        protected: tuple[str, ...],
    ) -> bytes:
        ctx.require(Permission.READ)
        binding = await self._projects.binding_of(ctx, project_id)
        if binding is None:
            raise Unavailable(f"project {project_id} binds no repository to validate")
        credential = await self._fetch_credential(ctx, project_id)
        return await self._reader.tree(binding, version, source, protected, credential)

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
        if stored is not None and _own_write(stored, allowlist, ctx):
            # A retry whose write landed before its answer was lost: the row
            # as stored, written once.
            return stored
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
                raced = await self._storage.read_allowlist(ctx.org_id, allowlist.project_id)
                if raced is not None and _own_write(raced, allowlist, ctx):
                    return raced
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

    # The repository's credentials, which the agent never holds.

    async def put_fetch_credential(
        self, ctx: TenantContext, project_id: UUID, credential: FetchCredential
    ) -> RepositoryCredential:
        ctx.require(Permission.MANAGE_MEMBERS)
        if await self._projects.binding_of(ctx, project_id) is None:
            raise NotFound(f"project {project_id} binds no repository of this tenant")
        now = self._clock()
        stored = await self._storage.read_credential(ctx.org_id, project_id)
        if stored is None:
            # The record lands before the value, so the purge finds every
            # value it must take out of the store.
            record = RepositoryCredential(
                id=project_id,
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
            )
            if not await self._storage.create_credential(ctx.org_id, record):
                raise PreconditionFailed(
                    f"the fetch credential of {project_id} was given meanwhile"
                )
        else:
            record = stored.model_copy(
                update={"version": stored.version + 1, "updated_at": now, "updated_by": ctx.user_id}
            )
            await self._storage.write_credential(ctx.org_id, record, stored.version)
        value = json.dumps(
            {"username": credential.username, "password": credential.password.get_secret_value()}
        )
        await self._secrets.put(
            ctx.org_id, rules.fetch_secret_name(project_id), value, deadline=ctx.deadline
        )
        log.info(
            "user %s of org %s gave project %s a fetch credential",
            ctx.user_id,
            ctx.org_id,
            project_id,
        )
        return record

    async def mint_push_token(self, ctx: TenantContext, session_id: UUID) -> PushToken:
        ctx.require(Permission.WRITE)
        held = await self._storage.read_workspace(ctx.org_id, session_id)
        if held is None:
            raise NotFound(f"session {session_id} has no workspace")
        binding = await self._binding(ctx, held)
        if binding is None:
            raise Unavailable(f"session {session_id} works on no bound repository")
        token = rules.PUSH_TOKEN_PREFIX + secrets.token_urlsafe(32)
        expires_at = self._clock() + self._options.push_token_lifetime
        await self._write(
            ctx, session_id, {"push_digest": hash_token(token), "push_expires_at": expires_at}
        )
        return PushToken(
            token=SecretStr(token),
            repository=binding.repository,
            branch=held.branch,
            expires_at=expires_at,
        )

    async def open_pull_request(
        self, ctx: TenantContext, session_id: UUID, token: str, head: str, title: str, body: str
    ) -> OpenedPullRequest:
        ctx.require(Permission.WRITE)
        held = await self._storage.read_workspace(ctx.org_id, session_id)
        if held is None:
            raise NotFound(f"session {session_id} has no workspace")
        binding = await self._binding(ctx, held)
        if binding is None:
            raise Unavailable(f"session {session_id} works on no bound repository")
        if not rules.COMMIT.fullmatch(head):
            raise ValidationFailed("the head of a pull request is a commit's full id")
        refusal = rules.body_refusal(body, binding)
        if refusal is not None:
            raise ValidationFailed(refusal)
        digest, now = hash_token(token), self._clock()
        for write in (
            RepositoryWrite(
                repository=binding.repository, kind=WriteKind.PUSH, ref=f"refs/heads/{held.branch}"
            ),
            RepositoryWrite(
                repository=binding.repository, kind=WriteKind.PULL_REQUEST, ref=held.branch
            ),
        ):
            refusal = rules.push_refusal(held, binding, digest, write, now)
            if refusal is not None:
                log.warning(
                    "session %s of org %s: a push token was refused: %s",
                    session_id,
                    ctx.org_id,
                    refusal,
                )
                raise NotAuthorized(refusal)
        workspace = self._held.get(session_id)
        if workspace is None:
            raise Unavailable(f"the workspace of session {session_id} is not held here")
        epoch = self._epoch(session_id)
        # The session's commits go out as a bundle the platform makes, and
        # source control pushes the one head to the session's branch alone.
        bundle = await self._git.outgoing(ctx, workspace, head, epoch=epoch)
        await self._source_control.push(ctx, binding, f"refs/heads/{held.branch}", head, bundle)
        await self._git.landed(ctx, workspace, held.branch, head, epoch=epoch)
        if not held.branch_seen:
            await self._write(ctx, session_id, {"branch_seen": True})
        return await self._source_control.open_pull_request(ctx, binding, held.branch, title, body)

    async def purge_session(self, org_id: UUID, session_id: UUID) -> bool:
        return await self._storage.purge_workspace(org_id, session_id)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        # Each fetch credential's value leaves the store before its record,
        # and the records that go are exactly the ones whose values went.
        held = await self._storage.read_credentials(ctx.org_id, self._options.purge_batch)
        for record in held:
            await self._secrets.delete(
                ctx.org_id, rules.fetch_secret_name(record.id), deadline=ctx.deadline
            )
        gone = await self._storage.purge_credentials(ctx.org_id, [record.id for record in held])
        return gone + await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    # Helpers.

    def _epoch(self, session_id: UUID) -> int:
        """The epoch of the run that holds the session's workspace here: a
        command for a tool of that run carries it."""
        epoch = self._held.epoch_of(session_id)
        if epoch is None:
            raise Unavailable(f"the workspace of session {session_id} is not held here")
        return epoch

    async def _fetch_credential(
        self, ctx: TenantContext, project_id: UUID
    ) -> FetchCredential | None:
        """The project's fetch credential, from the tenant's store, for the
        one read that asks; None when the project was given none."""
        if await self._storage.read_credential(ctx.org_id, project_id) is None:
            return None
        try:
            value = await self._secrets.get(
                ctx.org_id, rules.fetch_secret_name(project_id), deadline=ctx.deadline
            )
        except InfraException as failed:
            if failed.code != SECRET_NOT_FOUND:
                raise
            raise Unavailable(f"the fetch credential of project {project_id} is gone") from None
        try:
            return FetchCredential.model_validate_json(value)
        except ValidationError:
            raise Unavailable(f"the fetch credential of project {project_id} is not one") from None

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
        branch_seen: bool,
        snapshot_ref: str | None = None,
        forget_snapshot: bool = False,
        told: tuple[str, ...] = (),
        adds: str | None = None,
    ) -> None:
        """The cache's state, written over the stored row; the loop's push
        token, if one is live, ends with it. A snapshot is kept when one is
        given, and cleared when it is forgotten."""
        changes: dict[str, object] = {
            "branch_seen": branch_seen,
            "push_digest": None,
            "push_expires_at": None,
        }
        if snapshot_ref is not None or forget_snapshot:
            changes["snapshot_ref"] = snapshot_ref
        await self._write(ctx, session_id, changes, told=told, adds=adds)

    async def _write(
        self,
        ctx: TenantContext,
        session_id: UUID,
        fields: dict[str, object],
        *,
        told: tuple[str, ...] = (),
        adds: str | None = None,
    ) -> None:
        """`fields` written over the stored row, read again when a writer
        landed first. Its notices are never written over: those an attach
        `told` leave, compared against the row as stored, so one a release
        wrote meanwhile stays for the next loop; the one a release `adds`
        joins any not yet told."""
        for attempt in range(self._options.write_tries):
            stored = await self._storage.read_workspace(ctx.org_id, session_id)
            if stored is None:
                return
            notices = tuple(n for n in stored.notices if n not in told)
            changes = {
                **fields,
                "notices": notices if adds is None else (*notices, adds),
                "version": stored.version + 1,
                "updated_at": self._clock(),
                "updated_by": ctx.user_id,
            }
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


def _own_write(stored: EgressAllowlist, asked: EgressAllowlist, ctx: TenantContext) -> bool:
    """Whether the stored row is the caller's write landed already: its id
    and terms, at the version the caller read when it created the row, or
    the one after when the caller's own update made it."""
    if stored.id != asked.id:
        return False
    if (stored.rules, stored.open, stored.reason) != (asked.rules, asked.open, asked.reason):
        return False
    if stored.version == asked.version:
        return stored.version == 1 and stored.created_by == ctx.user_id
    return stored.version == asked.version + 1 and stored.updated_by == ctx.user_id
