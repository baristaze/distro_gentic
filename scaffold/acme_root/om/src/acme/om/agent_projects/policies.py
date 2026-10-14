"""What a namespace that keys a policy by agent project reads of the agent projects: the
agent project a session belongs to, and whether an agent project is the tenant's.

A budget, a secret, a validation policy, and the paths it protects are set
per agent project, and each is read through the session's agent project: the answer
`AgentProjectsManagerInterface.agent_project_of` gives, by id. The agent projects own both
answers; a root reads them from the agent projects' rows
(`acme.om.agent_projects.impl.policies.SessionAgentProjectsBoundImpl`)."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext


class SessionAgentProjectsInterface(ABC):
    @abstractmethod
    async def agent_project_of(self, ctx: TenantContext, session_id: UUID) -> UUID | None:
        """The id of the agent project the session belongs to; None for a session
        of no agent project, never another agent project."""
        ...

    @abstractmethod
    async def holds(self, ctx: TenantContext, agent_project_id: UUID) -> bool:
        """Whether the agent project is one of the caller's tenant. Another
        tenant's agent project is not, as one that never existed is not."""
        ...
