"""The tenant's retention: how long its sessions' content and shape are kept,
and one session's content erased before then. Any member reads the policy;
an owner or an admin writes it whole, on the version they read, and erases
a session's content."""

from uuid import UUID

from fastapi import APIRouter

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.precondition import IfMatch
from acme.services.api.gateway.resolve import RetentionService
from acme.services.api.types.retention import (
    RetentionRequest,
    RetentionView,
    SessionRetentionView,
)

router = APIRouter(prefix="/retention", tags=["retention"])


@router.get("/policy", response_model=RetentionView)
async def get_policy(ctx: Ctx, retention: RetentionService) -> RetentionView:
    return await retention.get_policy(ctx)


@router.put("/policy", response_model=RetentionView)
async def write_policy(
    ctx: Ctx, retention: RetentionService, body: RetentionRequest, version: IfMatch
) -> RetentionView:
    """The policy as written, on the version `If-Match` names; with no
    `If-Match`, the tenant's first. `412 precondition_failed` when the
    policy moved, or when a first meets one declared. Sessions created from
    now on take it; existing ones take what it tightens at the next sweep,
    and nothing it loosens."""
    return await retention.write_policy(ctx, body, version)


@router.post("/sessions/{session_id}/erase", response_model=SessionRetentionView)
async def erase_content(
    ctx: Ctx, retention: RetentionService, session_id: UUID
) -> SessionRetentionView:
    """Erases what the session said, for good: its key is revoked and
    destroyed, and the audit holds the destruction. Its steps keep their
    place, type, and shape, and read as saying nothing; the session takes no
    content again. A session marked deleted is erased too. Once: a second
    call answers as the first left it. `404 not_found` for a session the
    tenant does not hold, which is how another tenant's reads."""
    return await retention.erase_content(ctx, session_id)
