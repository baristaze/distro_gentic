"""The tenant's calls held for a person's decision, across its sessions,
a page of parked sessions at a time. A call is decided on its session's
own route."""

from fastapi import APIRouter

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.resolve import AgentSessionsService
from acme.services.api.types.agent_sessions import ApprovalPageView
from acme.services.api.types.common import LIMIT_DEFAULT

router = APIRouter(prefix="/approvals", tags=["agent_sessions"])


@router.get("", response_model=ApprovalPageView)
async def list_approvals(
    ctx: Ctx,
    sessions: AgentSessionsService,
    cursor: str | None = None,
    limit: int = LIMIT_DEFAULT,
) -> ApprovalPageView:
    return await sessions.get_org_approvals(ctx, cursor, limit)
