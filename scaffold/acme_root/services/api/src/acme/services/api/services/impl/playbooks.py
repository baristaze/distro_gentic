from acme.om.context import TenantContext
from acme.om.playbooks import PlaybooksManagerInterface
from acme.om.playbooks.types.playbook import PlaybookDraft
from acme.services.api.services.impl.built import built
from acme.services.api.services.playbooks import PlaybooksServiceInterface
from acme.services.api.types.playbooks import PlaybookView, PublishRequest


class PlaybooksServiceImpl(PlaybooksServiceInterface):
    def __init__(self, playbooks: PlaybooksManagerInterface) -> None:
        self._playbooks = playbooks

    async def publish(self, ctx: TenantContext, body: PublishRequest) -> PlaybookView:
        draft = built(PlaybookDraft, body.model_dump())
        return PlaybookView.model_validate(await self._playbooks.publish(ctx, draft))

    async def get_playbook(self, ctx: TenantContext, name: str) -> PlaybookView:
        return PlaybookView.model_validate(await self._playbooks.get_playbook(ctx, name))
