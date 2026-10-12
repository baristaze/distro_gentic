"""A tenant's playbooks: a person publishes a name's next version, in
person, and the latest version of a name is read. A person invokes the
latest version into a session they may instruct, and pins one to a kind
as its manual, which each session of the kind made after holds."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response

from acme.om.attribution.types.principal import MAX_KIND
from acme.om.playbooks.types.playbook import MAX_SKILL_NAME, SKILL_NAME
from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.resolve import PlaybooksService
from acme.services.api.types.playbooks import (
    InvocationView,
    InvokeRequest,
    PinRequest,
    PinView,
    PlaybookView,
    PublishRequest,
)

router = APIRouter(prefix="/playbooks", tags=["playbooks"])
pins = APIRouter(prefix="/playbook-pins", tags=["playbooks"])

PlaybookName = Annotated[str, Path(max_length=MAX_SKILL_NAME, pattern=SKILL_NAME)]


@router.post("", response_model=PlaybookView, status_code=201)
async def publish(
    ctx: Ctx, playbooks: PlaybooksService, body: PublishRequest, idem: Idem
) -> Response:
    """The next version of the name."""
    return await idem.run(201, lambda attempt: playbooks.publish(ctx, body, attempt.target_id))


@router.get("/{name}", response_model=PlaybookView)
async def get_playbook(ctx: Ctx, playbooks: PlaybooksService, name: PlaybookName) -> PlaybookView:
    """The latest version of the name."""
    return await playbooks.get_playbook(ctx, name)


@router.post("/{name}/invocations", response_model=InvocationView, status_code=201)
async def invoke(
    ctx: Ctx, playbooks: PlaybooksService, name: PlaybookName, body: InvokeRequest, idem: Idem
) -> Response:
    """The latest version brought into the session: its gates hold there
    from now on, and its brief arrives as the caller's message. Invoked
    again, the version's invocation answers, and nothing is sent twice."""
    return await idem.run(201, lambda _attempt: playbooks.invoke(ctx, name, body))


@pins.get("", response_model=list[PinView])
async def list_pins(ctx: Ctx, playbooks: PlaybooksService) -> list[PinView]:
    """The tenant's pins, by kind, the tenant's before a project's."""
    return await playbooks.pins(ctx)


@pins.put("", response_model=PinView)
async def pin(ctx: Ctx, playbooks: PlaybooksService, body: PinRequest) -> PinView:
    """The name's latest version pinned to the kind as its manual, for the
    tenant or one project; pinned again, the version then latest."""
    return await playbooks.pin(ctx, body)


@pins.delete("", response_model=PinView)
async def unpin(
    ctx: Ctx,
    playbooks: PlaybooksService,
    kind: Annotated[str, Query(min_length=1, max_length=MAX_KIND)],
    project_id: UUID | None = None,
) -> PinView:
    """The kind's pin for the tenant, or for one project, taken away. A
    session made with it keeps it."""
    return await playbooks.unpin(ctx, kind, project_id)
