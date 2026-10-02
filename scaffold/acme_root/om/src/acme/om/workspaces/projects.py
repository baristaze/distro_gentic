"""What the workspaces read of a session's project: which project it belongs
to, which keys the allowlist it pins, and the one repository that project
binds, where its branch and pull request are its work product.

The projects own both answers; a root reads them from the projects' rows
(`acme.om.workspaces.impl.projects.WorkspaceProjectsBoundImpl`). The null
answers none: a session keeps its kind's egress, has no checkout, and every
write it makes to source control acts outward
(`acme.om.workspaces.impl.projects.WorkspaceProjectsNullImpl`)."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.context import TenantContext
from acme.om.workspaces.types.source import PullRequestFate, RepositoryBinding


class WorkspaceProjectsInterface(ABC):
    @abstractmethod
    async def project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        """The project `session` belongs to, or None for one of no project.
        Asked once, before the session is written, and never again."""
        ...

    @abstractmethod
    async def binding_of(self, ctx: TenantContext, project_id: UUID) -> RepositoryBinding | None:
        """The repository the tenant's project binds, or None when it binds
        none."""
        ...


class PullRequestsInterface(ABC):
    """What source control says of a session's branch that is gone. The null
    knows nothing, so a vanished branch is never rebuilt on a guess
    (`acme.om.workspaces.impl.projects.PullRequestsNullImpl`)."""

    @abstractmethod
    async def fate_of(
        self, ctx: TenantContext, binding: RepositoryBinding, branch: str
    ) -> PullRequestFate | None:
        """Merged or closed when the pull request whose head is `branch` on
        the bound repository was; None when there is none, or it is open, or
        source control cannot say."""
        ...
