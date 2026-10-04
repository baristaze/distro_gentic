"""The workspaces swimlane: a session's workspace as a cache of durable
state. Its isolation is pinned when the session is created, and every
prepare after is held to that pin. Before a loop, the session's branch is
brought into the checkout, and a branch that vanished is rebuilt only when
source control says why. Before an instance goes, the work it holds is
pushed to a snapshot ref, and the next loop is told. A workspace's egress
is its project's allowlist of destinations and methods, and what it never
reaches it never reaches; a session's own branch and pull request on its
project's repository are its work product, and every other write acts
outward. The platform reaches that repository with two credentials the
agent never holds: the project's read-only fetch credential, where it reads
what a session delivered, and a push token that writes the session's own
branch and pull request, for one loop at most."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.infra.workspaces import IsolationSpec, Workspace
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.context import TenantContext
from acme.om.evidence.types.validation import Delivery
from acme.om.workspaces.types.credential import FetchCredential, PushToken, RepositoryCredential
from acme.om.workspaces.types.egress import EgressAllowlist, EgressDecision, EgressRequest
from acme.om.workspaces.types.source import OpenedPullRequest, RepositoryWrite
from acme.om.workspaces.types.workspace import SessionWorkspace


class WorkspacesManagerInterface(ABC):
    # The pin, and the cache around a loop.

    @abstractmethod
    async def pin(self, ctx: TenantContext, session: AgentSession) -> SessionWorkspace | None:
        """Pins a new session's isolation before it is written: its kind's
        level and limits at the version it starts on, and the egress its
        project allows now (`rules.pinned_egress`). Pinned once: a session
        pinned already is answered as stored. None, with nothing pinned, for
        a kind this process does not declare: no loop of it runs here, and
        one that runs elsewhere finds no pin and gets no workspace.
        `ValidationFailed` for egress a kind names that no allowlist can
        hold."""
        ...

    @abstractmethod
    async def get_workspace(self, ctx: TenantContext, session_id: UUID) -> SessionWorkspace:
        """The session's workspace as pinned and as the cache knows it;
        `NotFound` when it was never pinned."""
        ...

    @abstractmethod
    async def pinned(
        self, ctx: TenantContext, session_id: UUID, asked: IsolationSpec
    ) -> IsolationSpec:
        """The isolation every prepare of the session's workspace is held to:
        the pin, whatever a loop asks. A session never pinned, created
        before pins or by a process that does not declare its kind, is
        pinned at its first prepare that asks for a workspace, to what that
        loop asks, and held to it from then on."""
        ...

    @abstractmethod
    async def attach(self, ctx: TenantContext, workspace: Workspace, epoch: int) -> Workspace:
        """The prepared workspace, its checkout brought up to the session's
        branch on the repository its project binds (`rules.branch_plan`), and
        what the loop is told of it in `changed`: the snapshot of every
        instance let go since a loop was last told, and a branch rebuilt
        after its pull request closed. A branch the remote held and lost with
        no known fate is `WorkspaceLost`, which parks the loop for a person,
        and nothing is checked out from the default branch in its stead. A session whose project binds no
        repository has no checkout. Every command in the checkout carries
        `epoch`, the one the run that prepares it held when it began."""
        ...

    @abstractmethod
    async def detach(self, ctx: TenantContext, workspace: Workspace, epoch: int) -> None:
        """Before the workspace's instance goes: what its checkout holds that
        the remote lacks is committed and pushed to a snapshot ref, and the
        next loop will be told, beside any notice it has not yet read. Raises
        when it is not pushed, so the caller lets nothing go that is not
        kept. Every command carries `epoch`, the one the run that lets it go
        held when it began."""
        ...

    @abstractmethod
    async def delivery(self, ctx: TenantContext, workspace: Workspace) -> Delivery:
        """The session's work product: its branch as the bound repository
        holds it, read outside the workspace (`RepositoryReaderInterface`),
        with the repository's name as its project, the base its branch
        started from, its head, and the paths changed from the base; and
        dirty when the checkout holds work that is not there, uncommitted or
        not pushed. `Unavailable` for a session whose project binds no
        repository: nothing says what its work product is, so no success
        counts on a guess."""
        ...

    @abstractmethod
    async def checks_tree(
        self,
        ctx: TenantContext,
        project_id: UUID,
        version: str,
        source: str,
        protected: tuple[str, ...],
        source_project: UUID,
        base: str | None = None,
        untouched: tuple[str, ...] = (),
    ) -> bytes:
        """Platform-internal: the tree a validation of the project runs on,
        as a tar, read from its bound repository outside every workspace
        with its fetch credential (`RepositoryReaderInterface.tree`): the
        commit `version`, with every path a `protected` pattern matches
        taken from the commit `source` of the repository `source_project`
        binds, read with that project's fetch credential: the project's
        own, or a hidden suite's of the same tenant. With `base`, every
        other path an `untouched` pattern matches is taken from the
        project's own commit `base`. No credential and no history goes
        with it. `Unavailable` when either project binds no repository, or
        a commit cannot be read."""
        ...

    # Egress, and what acts outward.

    @abstractmethod
    async def get_allowlist(self, ctx: TenantContext, project_id: UUID) -> EgressAllowlist | None:
        """The project's allowlist, or None when it has written none."""
        ...

    @abstractmethod
    async def write_allowlist(
        self, ctx: TenantContext, allowlist: EgressAllowlist
    ) -> EgressAllowlist:
        """Writes the project's allowlist, as one who manages the tenant's
        members may: the first write creates it, and each later one is a
        compare-and-set on the version the caller read (`PreconditionFailed`
        when another landed first). Open egress is a choice it records with
        its reason and who made it. Announced like any change. It reaches
        the sessions created from then on; each one created before keeps the
        egress it pinned."""
        ...

    @abstractmethod
    async def egress(
        self, ctx: TenantContext, session_id: UUID, request: EgressRequest
    ) -> EgressDecision:
        """The egress proxy's answer to one connection of the session's
        workspace, by the egress it pinned (`rules.egress_decision`): a
        metadata endpoint, the host itself, and the platform's internal
        network never; then none, open, or the allowlist's
        destinations and methods. A session never pinned reaches nothing."""
        ...

    @abstractmethod
    async def outward(self, ctx: TenantContext, session_id: UUID, write: RepositoryWrite) -> bool:
        """Whether a write to source control acts outward, for the rule of
        two: every write but a push to the session's own branch or its
        snapshots, and its own pull request, on the one repository its
        project binds. A tool that writes there sets its target's `outward`
        from this."""
        ...

    # The repository's credentials, which the agent never holds.

    @abstractmethod
    async def put_fetch_credential(
        self, ctx: TenantContext, project_id: UUID, credential: FetchCredential
    ) -> RepositoryCredential:
        """Gives the platform a read-only credential of the repository the
        tenant's project binds, as one who manages the tenant's members may;
        a later one replaces it. Its value goes to the tenant's store under
        the project, and the record kept here says only who gave it and when.
        The platform reads a session's work product with it (`delivery`),
        and uses it nowhere else. `NotFound` for a project that binds no
        repository of the tenant's."""
        ...

    @abstractmethod
    async def remove_fetch_credential(self, ctx: TenantContext, project_id: UUID) -> bool:
        """Takes a project's fetch credential away, as one who manages the
        tenant's members may: its value leaves the tenant's store before its
        record goes. False when the project had none in this tenant. Asks
        nothing of the project, so a removed project's credential goes too."""
        ...

    @abstractmethod
    async def mint_push_token(self, ctx: TenantContext, session_id: UUID) -> PushToken:
        """A push token for the session's own branch on the repository its
        project binds: it writes that branch, its snapshots, and its pull
        request, and nothing else, until its lifetime passes or the loop's
        workspace is prepared again or released, whichever is first. Only its
        digest is kept, and a new one replaces the last. `NotFound` for a
        session never pinned, `Unavailable` for one whose project binds no
        repository."""
        ...

    @abstractmethod
    async def open_pull_request(
        self, ctx: TenantContext, session_id: UUID, token: str, head: str, title: str, body: str
    ) -> OpenedPullRequest:
        """Points the session's branch at the commit `head` and opens its pull
        request onto the repository's default branch, through source control,
        once the push token reaches both writes (`rules.push_refusal`):
        `NotAuthorized`, naming why, when it does not. A body that would make
        the forge fetch a URL off the repository's host is `ValidationFailed`
        before anything is pushed (`rules.body_refusal`). A refusal of source
        control's is `ValidationFailed`, and its absence `Unavailable`."""
        ...

    @abstractmethod
    async def purge_session(self, org_id: UUID, session_id: UUID) -> bool:
        """Platform-internal: the workspace row of a session the sweep has
        claimed for its purge goes with its history, in the tenant named;
        for no principal. False when none was left."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its workspaces,
        its allowlists, and its fetch credentials, each value out of the store
        before its record. Any other tenant returns 0 and reads nothing."""
        ...
