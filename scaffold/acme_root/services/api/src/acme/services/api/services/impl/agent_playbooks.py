from uuid import UUID

from acme.om.agent_playbooks import AgentPlaybooksManagerInterface
from acme.om.agent_playbooks.types.agent_playbook import AgentPlaybookDraft
from acme.om.context import TenantContext
from acme.services.api.services.agent_playbooks import AgentPlaybooksServiceInterface
from acme.services.api.services.impl.built import built
from acme.services.api.types.agent_playbooks import (
    AgentPlaybookView,
    InvocationView,
    InvokeRequest,
    PinRequest,
    PinView,
    PublishRequest,
)


class AgentPlaybooksServiceImpl(AgentPlaybooksServiceInterface):
    def __init__(self, agent_playbooks: AgentPlaybooksManagerInterface) -> None:
        self._agent_playbooks = agent_playbooks

    async def publish(
        self, ctx: TenantContext, body: PublishRequest, agent_playbook_id: UUID
    ) -> AgentPlaybookView:
        draft = built(AgentPlaybookDraft, body.model_dump())
        published = await self._agent_playbooks.publish(
            ctx, draft, agent_playbook_id=agent_playbook_id
        )
        return AgentPlaybookView.model_validate(published)

    async def get_agent_playbook(self, ctx: TenantContext, name: str) -> AgentPlaybookView:
        return AgentPlaybookView.model_validate(
            await self._agent_playbooks.get_agent_playbook(ctx, name)
        )

    async def invoke(self, ctx: TenantContext, name: str, body: InvokeRequest) -> InvocationView:
        invocation = await self._agent_playbooks.invoke(ctx, body.agent_session_id, name)
        return InvocationView.model_validate(invocation)

    async def pin(self, ctx: TenantContext, body: PinRequest) -> PinView:
        pinned = await self._agent_playbooks.pin(ctx, body.kind, body.name, body.agent_project_id)
        return PinView.model_validate(pinned)

    async def unpin(self, ctx: TenantContext, kind: str, agent_project_id: UUID | None) -> PinView:
        return PinView.model_validate(
            await self._agent_playbooks.unpin(ctx, kind, agent_project_id)
        )

    async def pins(self, ctx: TenantContext) -> list[PinView]:
        return [PinView.model_validate(pin) for pin in await self._agent_playbooks.pins(ctx)]
