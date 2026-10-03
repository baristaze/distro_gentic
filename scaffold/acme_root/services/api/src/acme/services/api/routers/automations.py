"""The tenant's automation principal: read its grant, and grant it a role,
in person, never above the granter's own."""

from fastapi import APIRouter

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.resolve import AutomationsService
from acme.services.api.types.automations import AutomationPrincipalView, GrantRequest

router = APIRouter(prefix="/automations", tags=["automations"])


@router.get("/principal", response_model=AutomationPrincipalView)
async def get_principal(ctx: Ctx, automations: AutomationsService) -> AutomationPrincipalView:
    return await automations.get_principal(ctx)


@router.put("/principal", response_model=AutomationPrincipalView)
async def grant_principal(
    ctx: Ctx, automations: AutomationsService, body: GrantRequest
) -> AutomationPrincipalView:
    """The principal granted the role; a grant over a standing one keeps it."""
    return await automations.grant_principal(ctx, body)
