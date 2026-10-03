"""The tenant's tool policy: its layer of rules over the agent kinds'
defaults and under the platform's ceilings, and who approves each class of
call. Any member reads it; an owner or an admin writes it whole, on the
version they read."""

from fastapi import APIRouter

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.precondition import IfMatch
from acme.services.api.gateway.resolve import ToolsService
from acme.services.api.types.tools import ToolPolicyRequest, ToolPolicyView

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/policy", response_model=ToolPolicyView)
async def get_policy(ctx: Ctx, tools: ToolsService) -> ToolPolicyView:
    return await tools.get_policy(ctx)


@router.put("/policy", response_model=ToolPolicyView)
async def write_policy(
    ctx: Ctx, tools: ToolsService, body: ToolPolicyRequest, version: IfMatch
) -> ToolPolicyView:
    """The layer as written, on the version `If-Match` names."""
    return await tools.write_policy(ctx, body, version)
