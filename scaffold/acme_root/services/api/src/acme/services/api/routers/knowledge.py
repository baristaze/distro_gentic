"""A tenant's knowledge: the entries in a state, the suggestions waiting on
a review among them; one entry; an entry a person writes, edits on the
version they read, or reviews. A person's, in person, to write."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.om.knowledge.types.knowledge import KnowledgeStatus
from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.precondition import IfMatch
from acme.services.api.gateway.resolve import KnowledgeService
from acme.services.api.types.common import LIMIT_DEFAULT
from acme.services.api.types.knowledge import KnowledgeRequest, KnowledgeView, ReviewRequest

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("", response_model=list[KnowledgeView])
async def list_entries(
    ctx: Ctx,
    knowledge: KnowledgeService,
    status: KnowledgeStatus = KnowledgeStatus.REVIEWED,
    after: UUID | None = None,
    limit: int = LIMIT_DEFAULT,
) -> list[KnowledgeView]:
    """The entries in a state by id, after the id `after` names."""
    return await knowledge.list_entries(ctx, status, after, limit)


@router.get("/{entry_id}", response_model=KnowledgeView)
async def get_entry(ctx: Ctx, knowledge: KnowledgeService, entry_id: UUID) -> KnowledgeView:
    return await knowledge.get_entry(ctx, entry_id)


@router.post("", response_model=KnowledgeView, status_code=201)
async def write_entry(
    ctx: Ctx, knowledge: KnowledgeService, body: KnowledgeRequest, idem: Idem
) -> Response:
    """An entry a person writes, reviewed as it is written."""
    return await idem.run(201, lambda attempt: knowledge.write_entry(ctx, body, attempt.target_id))


@router.put("/{entry_id}", response_model=KnowledgeView)
async def edit_entry(
    ctx: Ctx,
    knowledge: KnowledgeService,
    entry_id: UUID,
    body: KnowledgeRequest,
    version: IfMatch,
) -> KnowledgeView:
    """The entry as edited, on the version `If-Match` names."""
    return await knowledge.edit_entry(ctx, entry_id, body, version)


@router.post("/{entry_id}/review", response_model=KnowledgeView)
async def review_entry(
    ctx: Ctx, knowledge: KnowledgeService, entry_id: UUID, body: ReviewRequest
) -> KnowledgeView:
    """A suggestion kept, so sessions recall it, or rejected."""
    return await knowledge.review_entry(ctx, entry_id, body)
