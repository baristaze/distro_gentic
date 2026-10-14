"""A tenant's agent playbooks: a person publishes a name's next version, in
person, and the latest version of a name is read. A person invokes the
latest version into a session they may instruct, and pins one to a kind
as its kind manual, which each session of the kind made after holds."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response

from acme.om.agent_playbooks.types.agent_playbook import MAX_SKILL_NAME, SKILL_NAME
from acme.om.attribution.types.principal import MAX_KIND
from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.platform_resolve import AgentPlaybooksService
from acme.services.api.types.agent_playbooks import (
    AgentPlaybookView,
    InvocationView,
    InvokeRequest,
    PinRequest,
    PinView,
    PublishRequest,
)

router = APIRouter(prefix="/agent-playbooks", tags=["agent_playbooks"])
pins = APIRouter(prefix="/agent-playbook-pins", tags=["agent_playbooks"])

AgentPlaybookName = Annotated[str, Path(max_length=MAX_SKILL_NAME, pattern=SKILL_NAME)]


@router.post("", response_model=AgentPlaybookView, status_code=201)
async def publish(
    ctx: Ctx, agent_playbooks: AgentPlaybooksService, body: PublishRequest, idem: Idem
) -> Response:
    """The next version of the name."""
    return await idem.run(
        201, lambda attempt: agent_playbooks.publish(ctx, body, attempt.target_id)
    )


@router.get("/{name}", response_model=AgentPlaybookView)
async def get_agent_playbook(
    ctx: Ctx, agent_playbooks: AgentPlaybooksService, name: AgentPlaybookName
) -> AgentPlaybookView:
    """The latest version of the name."""
    return await agent_playbooks.get_agent_playbook(ctx, name)


@router.post("/{name}/invocations", response_model=InvocationView, status_code=201)
async def invoke(
    ctx: Ctx,
    agent_playbooks: AgentPlaybooksService,
    name: AgentPlaybookName,
    body: InvokeRequest,
    idem: Idem,
) -> Response:
    """The latest version brought into the session: its gates hold there
    from now on, and its brief arrives as the caller's message. Invoked
    again, the version's invocation answers, and nothing is sent twice."""
    return await idem.run(201, lambda _attempt: agent_playbooks.invoke(ctx, name, body))


@pins.get("", response_model=list[PinView])
async def list_pins(ctx: Ctx, agent_playbooks: AgentPlaybooksService) -> list[PinView]:
    """The tenant's pins, by kind, the tenant's before an agent project's."""
    return await agent_playbooks.pins(ctx)


@pins.put("", response_model=PinView)
async def pin(ctx: Ctx, agent_playbooks: AgentPlaybooksService, body: PinRequest) -> PinView:
    """The name's latest version pinned to the kind as its kind manual, for the
    tenant or one agent project; pinned again, the version then latest."""
    return await agent_playbooks.pin(ctx, body)


@pins.delete("", response_model=PinView)
async def unpin(
    ctx: Ctx,
    agent_playbooks: AgentPlaybooksService,
    kind: Annotated[str, Query(min_length=1, max_length=MAX_KIND)],
    agent_project_id: UUID | None = None,
) -> PinView:
    """The kind's pin for the tenant, or for one agent project, taken away. A
    session made with it keeps it."""
    return await agent_playbooks.unpin(ctx, kind, agent_project_id)
