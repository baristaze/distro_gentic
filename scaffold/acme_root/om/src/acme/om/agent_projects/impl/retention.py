from uuid import UUID

from acme.om.agent_projects.storage import AgentProjectStorageInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.context import TenantContext
from acme.om.retention.agent_projects import SessionAgentProjectInterface


class SessionAgentProjectBoundImpl(SessionAgentProjectInterface):
    """Retention's question, answered from the row the agent projects' start wrote
    before the session: so an agent project's narrowing reaches its sessions. A
    session with no row takes its tenant's policy unnarrowed."""

    def __init__(self, storage: AgentProjectStorageInterface) -> None:
        self._storage = storage

    async def agent_project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        binding = await self._storage.read_binding(ctx.org_id, session.id)
        return None if binding is None else binding.agent_project_id
