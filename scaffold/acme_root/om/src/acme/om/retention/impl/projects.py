from uuid import UUID

from acme.infra.base import QuietNull
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.context import TenantContext
from acme.om.retention.projects import SessionProjectInterface


class SessionProjectNullImpl(SessionProjectInterface, QuietNull):
    """Every session as one of no project: each takes its tenant's policy,
    which a project only narrows."""

    async def project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        return None
