"""The agent_knowledge namespace's calls: what a tenant's sessions recall,
written, edited, read, and kept or dropped on review."""

from typing import Any
from uuid import UUID

from acme.client.transport import LIMIT_MAX, Transport
from acme.client.types.agent_knowledge import (
    AgentKnowledgeStatus,
    AgentKnowledgeView,
)


class AgentKnowledgeCalls(Transport):
    """Agent knowledge: its entries, their writes, and their review."""

    async def agent_knowledge(
        self,
        status: AgentKnowledgeStatus = AgentKnowledgeStatus.reviewed,
        *,
        after: UUID | None = None,
        limit: int = LIMIT_MAX,
    ) -> list[AgentKnowledgeView]:
        """The entries in a state; the suggestions are what waits on a review."""
        params: dict[str, Any] = {"status": status.value, "limit": limit}
        if after is not None:
            params["after"] = str(after)
        found = await self.request("GET", "/v1/agent-knowledge", params=params)
        return [AgentKnowledgeView.model_validate(entry) for entry in found]

    async def agent_knowledge_entry(self, entry_id: UUID) -> AgentKnowledgeView:
        read = await self.request("GET", f"/v1/agent-knowledge/{entry_id}")
        return AgentKnowledgeView.model_validate(read)

    async def write_agent_knowledge(
        self, title: str, trigger: list[str], text: str
    ) -> AgentKnowledgeView:
        written = await self.request(
            "POST", "/v1/agent-knowledge", json={"title": title, "trigger": trigger, "text": text}
        )
        return AgentKnowledgeView.model_validate(written)

    async def edit_agent_knowledge(
        self, entry_id: UUID, title: str, trigger: list[str], text: str, *, version: int
    ) -> AgentKnowledgeView:
        """The edit, on the version read; `precondition_failed` when it moved."""
        edited = await self.request(
            "PUT",
            f"/v1/agent-knowledge/{entry_id}",
            json={"title": title, "trigger": trigger, "text": text},
            if_match=version,
        )
        return AgentKnowledgeView.model_validate(edited)

    async def review_agent_knowledge(self, entry_id: UUID, *, keep: bool) -> AgentKnowledgeView:
        reviewed = await self.request(
            "POST", f"/v1/agent-knowledge/{entry_id}/review", json={"keep": keep}
        )
        return AgentKnowledgeView.model_validate(reviewed)
