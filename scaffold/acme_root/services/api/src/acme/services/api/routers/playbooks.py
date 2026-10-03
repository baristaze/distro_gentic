"""A tenant's playbooks: a person publishes a name's next version, in
person, and the latest version of a name is read."""

from typing import Annotated

from fastapi import APIRouter, Path

from acme.om.playbooks.types.playbook import MAX_SKILL_NAME, SKILL_NAME
from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.resolve import PlaybooksService
from acme.services.api.types.playbooks import PlaybookView, PublishRequest

router = APIRouter(prefix="/playbooks", tags=["playbooks"])

PlaybookName = Annotated[str, Path(max_length=MAX_SKILL_NAME, pattern=SKILL_NAME)]


@router.post("", response_model=PlaybookView, status_code=201)
async def publish(ctx: Ctx, playbooks: PlaybooksService, body: PublishRequest) -> PlaybookView:
    """The next version of the name. A retry publishes another, so it takes
    no Idempotency-Key."""
    return await playbooks.publish(ctx, body)


@router.get("/{name}", response_model=PlaybookView)
async def get_playbook(ctx: Ctx, playbooks: PlaybooksService, name: PlaybookName) -> PlaybookView:
    """The latest version of the name."""
    return await playbooks.get_playbook(ctx, name)
