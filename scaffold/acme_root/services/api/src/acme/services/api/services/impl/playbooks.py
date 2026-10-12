from uuid import UUID

from acme.om.context import TenantContext
from acme.om.playbooks import PlaybooksManagerInterface
from acme.om.playbooks.types.playbook import PlaybookDraft
from acme.services.api.services.impl.built import built
from acme.services.api.services.playbooks import PlaybooksServiceInterface
from acme.services.api.types.playbooks import (
    InvocationView,
    InvokeRequest,
    PinRequest,
    PinView,
    PlaybookView,
    PublishRequest,
)


class PlaybooksServiceImpl(PlaybooksServiceInterface):
    def __init__(self, playbooks: PlaybooksManagerInterface) -> None:
        self._playbooks = playbooks

    async def publish(
        self, ctx: TenantContext, body: PublishRequest, playbook_id: UUID
    ) -> PlaybookView:
        draft = built(PlaybookDraft, body.model_dump())
        published = await self._playbooks.publish(ctx, draft, playbook_id=playbook_id)
        return PlaybookView.model_validate(published)

    async def get_playbook(self, ctx: TenantContext, name: str) -> PlaybookView:
        return PlaybookView.model_validate(await self._playbooks.get_playbook(ctx, name))

    async def invoke(self, ctx: TenantContext, name: str, body: InvokeRequest) -> InvocationView:
        invocation = await self._playbooks.invoke(ctx, body.session_id, name)
        return InvocationView.model_validate(invocation)

    async def pin(self, ctx: TenantContext, body: PinRequest) -> PinView:
        pinned = await self._playbooks.pin(ctx, body.kind, body.name, body.project_id)
        return PinView.model_validate(pinned)

    async def unpin(self, ctx: TenantContext, kind: str, project_id: UUID | None) -> PinView:
        return PinView.model_validate(await self._playbooks.unpin(ctx, kind, project_id))

    async def pins(self, ctx: TenantContext) -> list[PinView]:
        return [PinView.model_validate(pin) for pin in await self._playbooks.pins(ctx)]
