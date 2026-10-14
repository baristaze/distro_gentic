from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.om.agent_automations import AgentAutomationsManagerInterface
from acme.om.agent_automations.types.agent_automation import AgentAutomation
from acme.om.base import utcnow
from acme.om.context import TenantContext
from acme.services.api.services.agent_automations import AgentAutomationsServiceInterface
from acme.services.api.services.impl.built import built
from acme.services.api.types.agent_automations import (
    AgentAutomationPrincipalView,
    AgentAutomationRequest,
    AgentAutomationView,
    GrantRequest,
)


class AgentAutomationsServiceImpl(AgentAutomationsServiceInterface):
    def __init__(
        self,
        agent_automations: AgentAutomationsManagerInterface,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._agent_automations = agent_automations
        self._clock = clock

    async def get_principal(self, ctx: TenantContext) -> AgentAutomationPrincipalView:
        return AgentAutomationPrincipalView.model_validate(
            await self._agent_automations.get_principal(ctx)
        )

    async def grant_principal(
        self, ctx: TenantContext, body: GrantRequest
    ) -> AgentAutomationPrincipalView:
        granted = await self._agent_automations.grant_principal(ctx, body.role)
        return AgentAutomationPrincipalView.model_validate(granted)

    async def create_agent_automation(
        self, ctx: TenantContext, body: AgentAutomationRequest, agent_automation_id: UUID
    ) -> AgentAutomationView:
        made = await self._agent_automations.create_agent_automation(
            ctx, self._built(ctx, body, agent_automation_id)
        )
        return AgentAutomationView.model_validate(made)

    async def list_agent_automations(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> list[AgentAutomationView]:
        found = await self._agent_automations.list_agent_automations(ctx, after, limit)
        return [AgentAutomationView.model_validate(agent_automation) for agent_automation in found]

    async def get_agent_automation(
        self, ctx: TenantContext, agent_automation_id: UUID
    ) -> AgentAutomationView:
        found = await self._agent_automations.get_agent_automation(ctx, agent_automation_id)
        return AgentAutomationView.model_validate(found)

    async def update_agent_automation(
        self, ctx: TenantContext, agent_automation_id: UUID, body: AgentAutomationRequest
    ) -> AgentAutomationView:
        edited = await self._agent_automations.update_agent_automation(
            ctx, agent_automation_id, self._built(ctx, body, agent_automation_id)
        )
        return AgentAutomationView.model_validate(edited)

    def _built(
        self, ctx: TenantContext, body: AgentAutomationRequest, agent_automation_id: UUID
    ) -> AgentAutomation:
        """The agent automation as the body writes it; a field it leaves out takes
        the object model's default. Its provenance is the manager's: the
        create sets it, and an edit keeps the stored one."""
        now = self._clock()
        return built(
            AgentAutomation,
            {
                **body.model_dump(exclude_none=True),
                "id": agent_automation_id,
                "created_at": now,
                "updated_at": now,
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
            },
        )
