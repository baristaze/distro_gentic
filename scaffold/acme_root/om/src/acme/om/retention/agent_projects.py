"""Which agent project a new session belongs to, asked when its retention
snapshot is taken. The agent projects answer it, from the row their start
writes before the session (`acme.om.agent_projects.impl.retention`); a session
of no agent project, or a root that wires the null, takes its tenant's policy
unnarrowed."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.context import TenantContext


class SessionAgentProjectInterface(ABC):
    @abstractmethod
    async def agent_project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        """The agent project `session` belongs to, or None for a session of no
        agent project. Asked once, before the session is written."""
        ...
