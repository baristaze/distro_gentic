"""The playbooks service: a person publishes a playbook's next version, and
the latest version of a name is read."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.playbooks import PlaybookView, PublishRequest


class PlaybooksServiceInterface(ABC):
    @abstractmethod
    async def publish(
        self, ctx: TenantContext, body: PublishRequest, playbook_id: UUID
    ) -> PlaybookView: ...

    @abstractmethod
    async def get_playbook(self, ctx: TenantContext, name: str) -> PlaybookView: ...
