"""A tenant's automations, made, read, and edited by a person in person;
and the tenant's automation principal: read its grant, and grant it a role,
in person, never above the granter's own."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.resolve import AutomationsService
from acme.services.api.types.automations import (
    AutomationPrincipalView,
    AutomationRequest,
    AutomationView,
    GrantRequest,
)
from acme.services.api.types.common import LIMIT_DEFAULT

router = APIRouter(prefix="/automations", tags=["automations"])


# The principal's routes come before the ones an automation's id names, so
# `principal` is never read as an id.
@router.get("/principal", response_model=AutomationPrincipalView)
async def get_principal(ctx: Ctx, automations: AutomationsService) -> AutomationPrincipalView:
    return await automations.get_principal(ctx)


@router.put("/principal", response_model=AutomationPrincipalView)
async def grant_principal(
    ctx: Ctx, automations: AutomationsService, body: GrantRequest
) -> AutomationPrincipalView:
    """The principal granted the role; a grant over a standing one keeps it."""
    return await automations.grant_principal(ctx, body)


@router.post("", response_model=AutomationView, status_code=201)
async def create_automation(
    ctx: Ctx, automations: AutomationsService, body: AutomationRequest, idem: Idem
) -> Response:
    """An automation that runs as its maker, or as the automation principal."""
    return await idem.run(
        201, lambda attempt: automations.create_automation(ctx, body, attempt.target_id)
    )


@router.get("", response_model=list[AutomationView])
async def list_automations(
    ctx: Ctx, automations: AutomationsService, after: UUID | None = None, limit: int = LIMIT_DEFAULT
) -> list[AutomationView]:
    """The tenant's automations by id, after the id `after` names."""
    return await automations.list_automations(ctx, after, limit)


@router.get("/{automation_id}", response_model=AutomationView)
async def get_automation(
    ctx: Ctx, automations: AutomationsService, automation_id: UUID
) -> AutomationView:
    return await automations.get_automation(ctx, automation_id)


@router.put("/{automation_id}", response_model=AutomationView)
async def update_automation(
    ctx: Ctx, automations: AutomationsService, automation_id: UUID, body: AutomationRequest
) -> AutomationView:
    """The automation as edited. One that runs as its creator is edited by
    its creator alone; one that runs as the automation principal takes its
    editor as its creator."""
    return await automations.update_automation(ctx, automation_id, body)
