from uuid import UUID

from acme.infra.base import QuietNull
from acme.infra.workspaces import WorkspaceBase
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agent_workspaces.projects import PullRequestsInterface, WorkspaceProjectsInterface
from acme.om.agent_workspaces.types.source import PullRequestFate, RepositoryBinding
from acme.om.context import TenantContext
from acme.om.projects.storage import ProjectStorageInterface


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

    async def keeps_snapshots(self, ctx: TenantContext, project_id: UUID) -> bool:
        project = await self._storage.read_project(ctx.org_id, project_id)
        return project is None or project.workspace_snapshots

    async def workspace_base_of(self, ctx: TenantContext, project_id: UUID) -> WorkspaceBase | None:
        project = await self._storage.read_project(ctx.org_id, project_id)
        if project is None or project.workspace_base is None:
            return None
        return project.workspace_base.base()


class WorkspaceProjectsNullImpl(WorkspaceProjectsInterface, QuietNull):
    """No session belongs to a project yet: each keeps its kind's egress and
    its kind's base, has no checkout, and acts outward with every write to
    source control."""

    async def project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        return None

    async def binding_of(self, ctx: TenantContext, project_id: UUID) -> RepositoryBinding | None:
        return None

    async def keeps_snapshots(self, ctx: TenantContext, project_id: UUID) -> bool:
        return True

    async def workspace_base_of(self, ctx: TenantContext, project_id: UUID) -> WorkspaceBase | None:
        return None


class PullRequestsNullImpl(PullRequestsInterface, QuietNull):
    """Source control says nothing of a gone branch, so none is rebuilt."""

    async def fate_of(
        self, ctx: TenantContext, binding: RepositoryBinding, branch: str
    ) -> PullRequestFate | None:
        return None
