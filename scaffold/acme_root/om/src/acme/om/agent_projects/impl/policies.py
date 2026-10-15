from uuid import UUID

from acme.om.agent_projects.policies import SessionAgentProjectsInterface
from acme.om.agent_projects.storage import AgentProjectStorageInterface
from acme.om.context import TenantContext


class SessionAgentProjectsBoundImpl(SessionAgentProjectsInterface):
    """The agent projects' answers, from their rows: the one the agent projects' start,
    or the session's origin, wrote before the session, and the tenant's
    agent projects. A session with no row belongs to no agent project."""

    def __init__(self, storage: AgentProjectStorageInterface) -> None:
        self._storage = storage

    async def agent_project_of(self, ctx: TenantContext, agent_session_id: UUID) -> UUID | None:
        binding = await self._storage.read_binding(ctx.org_id, agent_session_id)
        return None if binding is None else binding.agent_project_id

    async def holds(self, ctx: TenantContext, agent_project_id: UUID) -> bool:
        return await self._storage.read_agent_project(ctx.org_id, agent_project_id) is not None


class SessionAgentProjectsNoneImpl(SessionAgentProjectsInterface):
    """A graph with no agent projects: every session belongs to none, and the
    tenant holds none."""

    async def agent_project_of(self, ctx: TenantContext, agent_session_id: UUID) -> UUID | None:
        return None

    async def holds(self, ctx: TenantContext, agent_project_id: UUID) -> bool:
        return False
