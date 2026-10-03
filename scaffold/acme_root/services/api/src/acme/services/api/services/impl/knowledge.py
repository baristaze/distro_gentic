from uuid import UUID

from acme.om.context import TenantContext
from acme.om.exceptions import ValidationFailed
from acme.om.knowledge import KnowledgeManagerInterface
from acme.om.knowledge.types.knowledge import KnowledgeStatus
from acme.services.api.services.knowledge import KnowledgeServiceInterface
from acme.services.api.types.knowledge import KnowledgeRequest, KnowledgeView, ReviewRequest


class KnowledgeServiceImpl(KnowledgeServiceInterface):
    def __init__(self, knowledge: KnowledgeManagerInterface) -> None:
        self._knowledge = knowledge

    async def list_entries(
        self, ctx: TenantContext, status: KnowledgeStatus, after: UUID | None, limit: int
    ) -> list[KnowledgeView]:
        found = await self._knowledge.list_entries(ctx, status, after, limit)
        return [KnowledgeView.model_validate(entry) for entry in found]

    async def get_entry(self, ctx: TenantContext, entry_id: UUID) -> KnowledgeView:
        return KnowledgeView.model_validate(await self._knowledge.get_entry(ctx, entry_id))

    async def write_entry(
        self, ctx: TenantContext, body: KnowledgeRequest, entry_id: UUID
    ) -> KnowledgeView:
        written = await self._knowledge.write(
            ctx, body.title, tuple(body.trigger), body.text, entry_id=entry_id
        )
        return KnowledgeView.model_validate(written)

    async def edit_entry(
        self, ctx: TenantContext, entry_id: UUID, body: KnowledgeRequest, version: int | None
    ) -> KnowledgeView:
        if version is None:
            raise ValidationFailed("an edit names the version it read, in If-Match")
        edited = await self._knowledge.edit(
            ctx, entry_id, body.title, tuple(body.trigger), body.text, version
        )
        return KnowledgeView.model_validate(edited)

    async def review_entry(
        self, ctx: TenantContext, entry_id: UUID, body: ReviewRequest
    ) -> KnowledgeView:
        reviewed = await self._knowledge.review(ctx, entry_id, keep=body.keep)
        return KnowledgeView.model_validate(reviewed)
