"""What the workspaces read of a session's agent project: which agent project it belongs
to, which keys the allowlist it pins, the one repository that agent project
binds, where its branch and pull request are its work product, and the
workspace base its workspace starts from. And the
source control that holds that repository: what it says of a gone branch,
and the writes that carry a session's commits to its branch or a snapshot
and open its pull request.

The agent projects own both answers; a root reads them from the agent projects' rows
(`acme.om.agent_workspaces.impl.agent_projects.WorkspaceAgentProjectsBoundImpl`). The null
answers none: a session keeps its kind's egress and its kind's base, has no
checkout, and every write it makes to source control acts outward
(`acme.om.agent_workspaces.impl.agent_projects.WorkspaceAgentProjectsNullImpl`)."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.infra.agent_workspaces import AgentWorkspaceBase
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agent_workspaces.types.source import (
    OpenedPullRequest,
    PullRequestFate,
    RepositoryBinding,
)
from acme.om.context import TenantContext


class WorkspaceAgentProjectsInterface(ABC):
    @abstractmethod
    async def agent_project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        """The agent project `session` belongs to, or None for one of no agent project.
        Asked once, before the session is written, and never again."""
        ...

    @abstractmethod
    async def binding_of(
        self, ctx: TenantContext, agent_project_id: UUID
    ) -> RepositoryBinding | None:
        """The repository the tenant's agent project binds, or None when it binds
        none."""
        ...

    @abstractmethod
    async def keeps_snapshots(self, ctx: TenantContext, agent_project_id: UUID) -> bool:
        """Whether the tenant's agent project lets a kind keep its workspace by
        snapshots; False keeps each of its sessions' workspaces a cache. An
        agent project the tenant does not hold narrows nothing."""
        ...

    @abstractmethod
    async def workspace_base_of(
        self, ctx: TenantContext, agent_project_id: UUID
    ) -> AgentWorkspaceBase | None:
        """The base the tenant's agent project names for its sessions' workspaces:
        its workspace base's image, setup, and the setup's egress. None when it
        names none, or the tenant does not hold it."""
        ...


class PullRequestsInterface(ABC):
    """What source control says of a session's branch that is gone. The null
    knows nothing, so a vanished branch is never rebuilt on a guess
    (`acme.om.agent_workspaces.impl.agent_projects.PullRequestsNullImpl`)."""

    @abstractmethod
    async def fate_of(
        self, ctx: TenantContext, binding: RepositoryBinding, branch: str
    ) -> PullRequestFate | None:
        """Merged or closed when the pull request whose head is `branch` on
        the bound repository was; None when there is none, or it is open, or
        source control cannot say."""
        ...


class SourceControlInterface(ABC):
    """The writes that open a session's branch and its pull request on its
    bound repository, as the platform's integration makes them, with its own
    credential, which never leaves it. The workspaces call it only for a
    write a session's push token reaches (`rules.push_refusal`), and each
    goes only to a repository an installation of `ctx`'s tenant holds:
    `NotAuthorized` for any other, before anything is written. A root wires
    the forge's (`acme.om.agent_workspaces.impl.forge.SourceControlForgeImpl`);
    with none, every write is `Unavailable`."""

    @abstractmethod
    async def push(
        self, ctx: TenantContext, binding: RepositoryBinding, ref: str, head: str, bundle: bytes
    ) -> None:
        """Points `ref` of the bound repository (a full name) at the commit
        `head`, forward only, carrying the commits it needs from `bundle`,
        the git bundle the platform made of them; nothing else in it is
        written."""
        ...

    @abstractmethod
    async def open_pull_request(
        self, ctx: TenantContext, binding: RepositoryBinding, branch: str, title: str, body: str
    ) -> OpenedPullRequest:
        """Opens the pull request of `branch` onto the repository's default
        branch, or answers the one open already."""
        ...
