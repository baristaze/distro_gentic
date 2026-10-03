"""A session's evidence and its delivery: the runs of its checks, its
validations, and what it delivered. Each function is one call into the
evidence service; another tenant's session answers as one that never
existed."""

from uuid import UUID

from fastapi import APIRouter

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.resolve import EvidenceService
from acme.services.api.types.common import LIMIT_DEFAULT
from acme.services.api.types.evidence import DeliveryView, ExecutionPageView, ValidationView

router = APIRouter(prefix="/agent-sessions", tags=["evidence"])


@router.get("/{session_id}/executions", response_model=ExecutionPageView)
async def list_executions(
    ctx: Ctx,
    evidence: EvidenceService,
    session_id: UUID,
    cursor: str | None = None,
    limit: int = LIMIT_DEFAULT,
) -> ExecutionPageView:
    """The runs of checks the session recorded or the executor ran for it,
    oldest first, a page at a time."""
    return await evidence.get_executions(ctx, session_id, cursor, limit)


@router.get("/{session_id}/validations", response_model=list[ValidationView])
async def list_validations(
    ctx: Ctx, evidence: EvidenceService, session_id: UUID, limit: int = LIMIT_DEFAULT
) -> list[ValidationView]:
    return await evidence.get_validations(ctx, session_id, limit)


@router.get("/{session_id}/delivery", response_model=DeliveryView)
async def get_delivery(ctx: Ctx, evidence: EvidenceService, session_id: UUID) -> DeliveryView:
    """Its branch, the pull requests and branches bound to it, and the result
    it submitted that the gate accepted."""
    return await evidence.get_delivery(ctx, session_id)
