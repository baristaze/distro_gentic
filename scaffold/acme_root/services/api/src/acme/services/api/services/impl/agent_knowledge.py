from uuid import UUID

from acme.om.agent_knowledge import AgentKnowledgeManagerInterface
from acme.om.agent_knowledge.types.agent_knowledge import AgentKnowledgeStatus
from acme.om.context import TenantContext
from acme.om.exceptions import ValidationFailed
from acme.services.api.services.agent_knowledge import AgentKnowledgeServiceInterface
from acme.services.api.types.agent_knowledge import (
    AgentKnowledgeRequest,
    AgentKnowledgeView,
    ReviewRequest,
)


class AgentKnowledgeServiceImpl(AgentKnowledgeServiceInterface):
    def __init__(self, agent_knowledge: AgentKnowledgeManagerInterface) -> None:
        self._agent_knowledge = agent_knowledge

    async def list_entries(
        self, ctx: TenantContext, status: AgentKnowledgeStatus, after: UUID | None, limit: int
    ) -> list[AgentKnowledgeView]:
        found = await self._agent_knowledge.list_entries(ctx, status, after, limit)
        return [AgentKnowledgeView.model_validate(entry) for entry in found]

    async def get_entry(self, ctx: TenantContext, entry_id: UUID) -> AgentKnowledgeView:
        return AgentKnowledgeView.model_validate(
            await self._agent_knowledge.get_entry(ctx, entry_id)
        )

    async def write_entry(
        self, ctx: TenantContext, body: AgentKnowledgeRequest, entry_id: UUID
    ) -> AgentKnowledgeView:
        written = await self._agent_knowledge.write(
            ctx, body.title, tuple(body.trigger), body.text, entry_id=entry_id
        )
        return AgentKnowledgeView.model_validate(written)

    async def edit_entry(
        self, ctx: TenantContext, entry_id: UUID, body: AgentKnowledgeRequest, version: int | None
    ) -> AgentKnowledgeView:
        if version is None:
            raise ValidationFailed("an edit names the version it read, in If-Match")
        edited = await self._agent_knowledge.edit(
            ctx, entry_id, body.title, tuple(body.trigger), body.text, version
        )
        return AgentKnowledgeView.model_validate(edited)

    async def review_entry(
        self, ctx: TenantContext, entry_id: UUID, body: ReviewRequest
    ) -> AgentKnowledgeView:
        reviewed = await self._agent_knowledge.review(ctx, entry_id, keep=body.keep)
        return AgentKnowledgeView.model_validate(reviewed)
