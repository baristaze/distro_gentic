"""The doubles of the platform's ports that its suites share."""

from uuid import UUID

from acme.om.agent_projects.policies import SessionAgentProjectsInterface
from acme.om.context import TenantContext


class SessionAgentProjectsMemory(SessionAgentProjectsInterface):
    """Each session's agent project as a suite names it: one it never named
    belongs to `default`, and a tenant holds the agent projects named here."""

    def __init__(self, default: UUID | None = None) -> None:
        self.default = default
        self.sessions: dict[UUID, UUID | None] = {}

    async def agent_project_of(self, ctx: TenantContext, agent_session_id: UUID) -> UUID | None:
        return self.sessions.get(agent_session_id, self.default)

    async def holds(self, ctx: TenantContext, agent_project_id: UUID) -> bool:
        return agent_project_id in {self.default, *self.sessions.values()}
