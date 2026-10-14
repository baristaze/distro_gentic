"""The agent playbooks service: a person publishes an agent playbook's next version, the
latest version of a name is read, a person invokes one into a session,
and pins one to a kind as its kind manual."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.agent_playbooks import (
    AgentPlaybookView,
    InvocationView,
    InvokeRequest,
    PinRequest,
    PinView,
    PublishRequest,
)


class AgentPlaybooksServiceInterface(ABC):
    @abstractmethod
    async def publish(
        self, ctx: TenantContext, body: PublishRequest, agent_playbook_id: UUID
    ) -> AgentPlaybookView: ...

    @abstractmethod
    async def get_agent_playbook(self, ctx: TenantContext, name: str) -> AgentPlaybookView: ...

    @abstractmethod
    async def invoke(
        self, ctx: TenantContext, name: str, body: InvokeRequest
    ) -> InvocationView: ...

    @abstractmethod
    async def pin(self, ctx: TenantContext, body: PinRequest) -> PinView: ...

    @abstractmethod
    async def unpin(
        self, ctx: TenantContext, kind: str, agent_project_id: UUID | None
    ) -> PinView: ...

    @abstractmethod
    async def pins(self, ctx: TenantContext) -> list[PinView]: ...
