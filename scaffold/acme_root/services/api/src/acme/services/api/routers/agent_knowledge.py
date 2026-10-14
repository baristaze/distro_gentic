"""A tenant's agent knowledge: the entries in a state, the suggestions waiting on
a review among them; one entry; an entry a person writes, edits on the
version they read, or reviews. A person's, in person, to write."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.om.agent_knowledge.types.agent_knowledge import AgentKnowledgeStatus
from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.platform_resolve import AgentKnowledgeService
from acme.services.api.gateway.precondition import IfMatch
from acme.services.api.types.agent_knowledge import (
    AgentKnowledgeRequest,
    AgentKnowledgeView,
    ReviewRequest,
)
from acme.services.api.types.common import LIMIT_DEFAULT

router = APIRouter(prefix="/agent-knowledge", tags=["agent_knowledge"])


@router.get("", response_model=list[AgentKnowledgeView])
async def list_entries(
    ctx: Ctx,
    agent_knowledge: AgentKnowledgeService,
    status: AgentKnowledgeStatus = AgentKnowledgeStatus.REVIEWED,
    after: UUID | None = None,
    limit: int = LIMIT_DEFAULT,
) -> list[AgentKnowledgeView]:
    """The entries in a state by id, after the id `after` names."""
    return await agent_knowledge.list_entries(ctx, status, after, limit)


@router.get("/{entry_id}", response_model=AgentKnowledgeView)
async def get_entry(
    ctx: Ctx, agent_knowledge: AgentKnowledgeService, entry_id: UUID
) -> AgentKnowledgeView:
    return await agent_knowledge.get_entry(ctx, entry_id)


@router.post("", response_model=AgentKnowledgeView, status_code=201)
async def write_entry(
    ctx: Ctx, agent_knowledge: AgentKnowledgeService, body: AgentKnowledgeRequest, idem: Idem
) -> Response:
    """An entry a person writes, reviewed as it is written."""
    return await idem.run(
        201, lambda attempt: agent_knowledge.write_entry(ctx, body, attempt.target_id)
    )


@router.put("/{entry_id}", response_model=AgentKnowledgeView)
async def edit_entry(
    ctx: Ctx,
    agent_knowledge: AgentKnowledgeService,
    entry_id: UUID,
    body: AgentKnowledgeRequest,
    version: IfMatch,
) -> AgentKnowledgeView:
    """The entry as edited, on the version `If-Match` names."""
    return await agent_knowledge.edit_entry(ctx, entry_id, body, version)


@router.post("/{entry_id}/review", response_model=AgentKnowledgeView)
async def review_entry(
    ctx: Ctx, agent_knowledge: AgentKnowledgeService, entry_id: UUID, body: ReviewRequest
) -> AgentKnowledgeView:
    """A suggestion kept, so sessions recall it, or rejected."""
    return await agent_knowledge.review_entry(ctx, entry_id, body)
