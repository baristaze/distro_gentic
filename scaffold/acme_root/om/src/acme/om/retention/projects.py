"""Which project a new session belongs to, asked when its retention
snapshot is taken. The platform's work intake knows it; until a session
carries it, the null answers none, and the session takes its tenant's
policy unnarrowed."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.context import TenantContext


class SessionProjectInterface(ABC):
    @abstractmethod
    async def project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        """The project `session` belongs to, or None for a session of no
        project. Asked once, before the session is written."""
        ...
