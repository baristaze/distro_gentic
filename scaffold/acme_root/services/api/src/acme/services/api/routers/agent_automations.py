"""A tenant's agent automations, made, read, and edited by a person in person;
and the tenant's agent automation principal: read its grant, and grant it a role,
in person, never above the granter's own."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.platform_resolve import AgentAutomationsService
from acme.services.api.types.agent_automations import (
    AgentAutomationPrincipalView,
    AgentAutomationRequest,
    AgentAutomationView,
    GrantRequest,
)
from acme.services.api.types.common import LIMIT_DEFAULT

router = APIRouter(prefix="/agent-automations", tags=["agent_automations"])


# The principal's routes come before the ones an agent automation's id names, so
# `principal` is never read as an id.
@router.get("/principal", response_model=AgentAutomationPrincipalView)
async def get_principal(
    ctx: Ctx, agent_automations: AgentAutomationsService
) -> AgentAutomationPrincipalView:
    return await agent_automations.get_principal(ctx)


@router.put("/principal", response_model=AgentAutomationPrincipalView)
async def grant_principal(
    ctx: Ctx, agent_automations: AgentAutomationsService, body: GrantRequest
) -> AgentAutomationPrincipalView:
    """The principal granted the role; a grant over a standing one keeps it."""
    return await agent_automations.grant_principal(ctx, body)


@router.post("", response_model=AgentAutomationView, status_code=201)
async def create_agent_automation(
    ctx: Ctx, agent_automations: AgentAutomationsService, body: AgentAutomationRequest, idem: Idem
) -> Response:
    """An agent automation that runs as its maker, or as the agent automation principal."""
    return await idem.run(
        201, lambda attempt: agent_automations.create_agent_automation(ctx, body, attempt.target_id)
    )


@router.get("", response_model=list[AgentAutomationView])
async def list_agent_automations(
    ctx: Ctx,
    agent_automations: AgentAutomationsService,
    after: UUID | None = None,
    limit: int = LIMIT_DEFAULT,
) -> list[AgentAutomationView]:
    """The tenant's agent automations by id, after the id `after` names."""
    return await agent_automations.list_agent_automations(ctx, after, limit)


@router.get("/{agent_automation_id}", response_model=AgentAutomationView)
async def get_agent_automation(
    ctx: Ctx, agent_automations: AgentAutomationsService, agent_automation_id: UUID
) -> AgentAutomationView:
    return await agent_automations.get_agent_automation(ctx, agent_automation_id)


@router.put("/{agent_automation_id}", response_model=AgentAutomationView)
async def update_agent_automation(
    ctx: Ctx,
    agent_automations: AgentAutomationsService,
    agent_automation_id: UUID,
    body: AgentAutomationRequest,
) -> AgentAutomationView:
    """The agent automation as edited. One that runs as its creator is edited by
    its creator alone; one that runs as the agent automation principal takes its
    editor as its creator."""
    return await agent_automations.update_agent_automation(ctx, agent_automation_id, body)
