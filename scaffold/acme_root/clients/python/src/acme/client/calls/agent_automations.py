"""The agent_automations namespace's calls: a tenant's agent automations,
made, listed, read, and rewritten."""

from typing import Any
from uuid import UUID, uuid4

from acme.client.transport import LIMIT_MAX, Transport
from acme.client.types.agent_automations import (
    AgentAutomationRequest,
    AgentAutomationView,
)


class AgentAutomationsCalls(Transport):
    """An agent automation's making, its reads, and its rewrite."""

    async def create_agent_automation(
        self, agent_automation: AgentAutomationRequest, *, idempotency_key: str | None = None
    ) -> AgentAutomationView:
        """Made in person; it runs as its maker unless it says otherwise.
        Always under an idempotency key."""
        made = await self.request(
            "POST",
            "/v1/agent-automations",
            json=agent_automation.model_dump(mode="json", exclude_unset=True),
            idempotency_key=idempotency_key or str(uuid4()),
        )
        return AgentAutomationView.model_validate(made)

    async def agent_automations(
        self, *, after: UUID | None = None, limit: int = LIMIT_MAX
    ) -> list[AgentAutomationView]:
        params: dict[str, Any] = {"limit": limit}
        if after is not None:
            params["after"] = str(after)
        found = await self.request("GET", "/v1/agent-automations", params=params)
        return [AgentAutomationView.model_validate(agent_automation) for agent_automation in found]

    async def agent_automation(self, agent_automation_id: UUID) -> AgentAutomationView:
        read = await self.request("GET", f"/v1/agent-automations/{agent_automation_id}")
        return AgentAutomationView.model_validate(read)

    async def update_agent_automation(
        self, agent_automation_id: UUID, agent_automation: AgentAutomationRequest
    ) -> AgentAutomationView:
        """The agent automation whole, as edited; one that runs as its creator is
        edited by its creator alone, and one that runs as the agent automation
        principal takes its editor as its creator."""
        edited = await self.request(
            "PUT",
            f"/v1/agent-automations/{agent_automation_id}",
            json=agent_automation.model_dump(mode="json", exclude_unset=True),
        )
        return AgentAutomationView.model_validate(edited)
