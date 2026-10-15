from uuid import UUID

from acme.infra.agent_workspaces import AgentWorkspaceBase
from acme.infra.base import QuietNull
from acme.om.agent_projects.storage import AgentProjectStorageInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agent_workspaces.agent_projects import (
    PullRequestsInterface,
    WorkspaceAgentProjectsInterface,
)
from acme.om.agent_workspaces.types.source import PullRequestFate, RepositoryBinding
from acme.om.context import TenantContext


class WorkspaceAgentProjectsBoundImpl(WorkspaceAgentProjectsInterface):
    """The agent projects' answers: the row a session's agent project start, or its
    origin, wrote before the session, and the one repository that agent project
    binds, cloned over HTTPS, cut from its own default branch."""

    def __init__(self, storage: AgentProjectStorageInterface) -> None:
        self._storage = storage

    async def agent_project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        binding = await self._storage.read_binding(ctx.org_id, session.id)
        return None if binding is None else binding.agent_project_id

    async def binding_of(
        self, ctx: TenantContext, agent_project_id: UUID
    ) -> RepositoryBinding | None:
        agent_project = await self._storage.read_agent_project(ctx.org_id, agent_project_id)
        if agent_project is None:
            return None
        repository = agent_project.repository
        return RepositoryBinding(
            agent_project_id=agent_project_id,
            repository=f"https://{repository.host}/{repository.path}.git",
        )

    async def keeps_snapshots(self, ctx: TenantContext, agent_project_id: UUID) -> bool:
        agent_project = await self._storage.read_agent_project(ctx.org_id, agent_project_id)
        return agent_project is None or agent_project.workspace_snapshots

    async def workspace_base_of(
        self, ctx: TenantContext, agent_project_id: UUID
    ) -> AgentWorkspaceBase | None:
        agent_project = await self._storage.read_agent_project(ctx.org_id, agent_project_id)
        if agent_project is None or agent_project.agent_workspace_base is None:
            return None
        return agent_project.agent_workspace_base.base()


class WorkspaceAgentProjectsNullImpl(WorkspaceAgentProjectsInterface, QuietNull):
    """No session belongs to an agent project yet: each keeps its kind's egress and
    its kind's base, has no checkout, and acts outward with every write to
    source control."""

    async def agent_project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        return None

    async def binding_of(
        self, ctx: TenantContext, agent_project_id: UUID
    ) -> RepositoryBinding | None:
        return None

    async def keeps_snapshots(self, ctx: TenantContext, agent_project_id: UUID) -> bool:
        return True

    async def workspace_base_of(
        self, ctx: TenantContext, agent_project_id: UUID
    ) -> AgentWorkspaceBase | None:
        return None


class PullRequestsNullImpl(PullRequestsInterface, QuietNull):
    """Source control says nothing of a gone branch, so none is rebuilt."""

    async def fate_of(
        self, ctx: TenantContext, binding: RepositoryBinding, branch: str
    ) -> PullRequestFate | None:
        return None
