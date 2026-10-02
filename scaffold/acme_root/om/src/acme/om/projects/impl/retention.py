from uuid import UUID

from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.context import TenantContext
from acme.om.projects.storage import ProjectStorageInterface
from acme.om.retention.projects import SessionProjectInterface


class SessionProjectBoundImpl(SessionProjectInterface):
    """Retention's question, answered from the row the projects' start wrote
    before the session: so a project's narrowing reaches its sessions. A
    session with no row takes its tenant's policy unnarrowed."""

    def __init__(self, storage: ProjectStorageInterface) -> None:
        self._storage = storage

    async def project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        binding = await self._storage.read_binding(ctx.org_id, session.id)
        return None if binding is None else binding.project_id
