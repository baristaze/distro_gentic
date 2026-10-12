"""The playbooks service: a person publishes a playbook's next version, the
latest version of a name is read, a person invokes one into a session,
and pins one to a kind as its manual."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.playbooks import (
    InvocationView,
    InvokeRequest,
    PinRequest,
    PinView,
    PlaybookView,
    PublishRequest,
)


class PlaybooksServiceInterface(ABC):
    @abstractmethod
    async def publish(
        self, ctx: TenantContext, body: PublishRequest, playbook_id: UUID
    ) -> PlaybookView: ...

    @abstractmethod
    async def get_playbook(self, ctx: TenantContext, name: str) -> PlaybookView: ...

    @abstractmethod
    async def invoke(
        self, ctx: TenantContext, name: str, body: InvokeRequest
    ) -> InvocationView: ...

    @abstractmethod
    async def pin(self, ctx: TenantContext, body: PinRequest) -> PinView: ...

    @abstractmethod
    async def unpin(self, ctx: TenantContext, kind: str, project_id: UUID | None) -> PinView: ...

    @abstractmethod
    async def pins(self, ctx: TenantContext) -> list[PinView]: ...
