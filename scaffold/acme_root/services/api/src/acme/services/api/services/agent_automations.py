"""The agent automations service: a person makes, reads, and edits the tenant's
agent_automations, and grants the tenant's agent automation principal a role."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.agent_automations import (
    AgentAutomationPrincipalView,
    AgentAutomationRequest,
    AgentAutomationView,
    GrantRequest,
)


class AgentAutomationsServiceInterface(ABC):
    @abstractmethod
    async def get_principal(self, ctx: TenantContext) -> AgentAutomationPrincipalView: ...

    @abstractmethod
    async def grant_principal(
        self, ctx: TenantContext, body: GrantRequest
    ) -> AgentAutomationPrincipalView: ...

    @abstractmethod
    async def create_agent_automation(
        self, ctx: TenantContext, body: AgentAutomationRequest, agent_automation_id: UUID
    ) -> AgentAutomationView: ...

    @abstractmethod
    async def list_agent_automations(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> list[AgentAutomationView]: ...

    @abstractmethod
    async def get_agent_automation(
        self, ctx: TenantContext, agent_automation_id: UUID
    ) -> AgentAutomationView: ...

    @abstractmethod
    async def update_agent_automation(
        self, ctx: TenantContext, agent_automation_id: UUID, body: AgentAutomationRequest
    ) -> AgentAutomationView: ...
