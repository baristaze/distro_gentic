from uuid import UUID

from acme.infra.base import QuietNull
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.context import TenantContext
from acme.om.workspaces.projects import PullRequestsInterface, WorkspaceProjectsInterface
from acme.om.workspaces.types.source import PullRequestFate, RepositoryBinding


class WorkspaceProjectsNullImpl(WorkspaceProjectsInterface, QuietNull):
    """No session belongs to a project yet: each keeps its kind's egress, has
    no checkout, and acts outward with every write to source control."""

    async def project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        return None

    async def binding_of(self, ctx: TenantContext, project_id: UUID) -> RepositoryBinding | None:
        return None


class PullRequestsNullImpl(PullRequestsInterface, QuietNull):
    """Source control says nothing of a gone branch, so none is rebuilt."""

    async def fate_of(
        self, ctx: TenantContext, binding: RepositoryBinding, branch: str
    ) -> PullRequestFate | None:
        return None
