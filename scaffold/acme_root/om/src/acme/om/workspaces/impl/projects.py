from uuid import UUID

from acme.infra.base import QuietNull
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.context import TenantContext
from acme.om.projects.storage import ProjectStorageInterface
from acme.om.workspaces.projects import PullRequestsInterface, WorkspaceProjectsInterface
from acme.om.workspaces.types.source import PullRequestFate, RepositoryBinding


class WorkspaceProjectsBoundImpl(WorkspaceProjectsInterface):
    """The projects' answers: the row a session's project start, or its
    origin, wrote before the session, and the one repository that project
    binds, cloned over HTTPS, cut from its own default branch."""

    def __init__(self, storage: ProjectStorageInterface) -> None:
        self._storage = storage

    async def project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        binding = await self._storage.read_binding(ctx.org_id, session.id)
        return None if binding is None else binding.project_id

    async def binding_of(self, ctx: TenantContext, project_id: UUID) -> RepositoryBinding | None:
        project = await self._storage.read_project(ctx.org_id, project_id)
        if project is None:
            return None
        repository = project.repository
        return RepositoryBinding(
            project_id=project_id, repository=f"https://{repository.host}/{repository.path}.git"
        )


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
