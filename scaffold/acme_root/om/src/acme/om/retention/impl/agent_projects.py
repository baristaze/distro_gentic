from uuid import UUID

from acme.infra.base import QuietNull
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.context import TenantContext
from acme.om.retention.agent_projects import SessionAgentProjectInterface


class SessionAgentProjectNullImpl(SessionAgentProjectInterface, QuietNull):
    """Every session as one of no agent project: each takes its tenant's policy,
    which an agent project only narrows."""

    async def agent_project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        return None
