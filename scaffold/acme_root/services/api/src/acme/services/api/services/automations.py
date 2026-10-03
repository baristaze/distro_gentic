"""The automations service: a person makes, reads, and edits the tenant's
automations, and grants the tenant's automation principal a role."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.automations import (
    AutomationPrincipalView,
    AutomationRequest,
    AutomationView,
    GrantRequest,
)


class AutomationsServiceInterface(ABC):
    @abstractmethod
    async def get_principal(self, ctx: TenantContext) -> AutomationPrincipalView: ...

    @abstractmethod
    async def grant_principal(
        self, ctx: TenantContext, body: GrantRequest
    ) -> AutomationPrincipalView: ...

    @abstractmethod
    async def create_automation(
        self, ctx: TenantContext, body: AutomationRequest, automation_id: UUID
    ) -> AutomationView: ...

    @abstractmethod
    async def list_automations(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> list[AutomationView]: ...

    @abstractmethod
    async def get_automation(self, ctx: TenantContext, automation_id: UUID) -> AutomationView: ...

    @abstractmethod
    async def update_automation(
        self, ctx: TenantContext, automation_id: UUID, body: AutomationRequest
    ) -> AutomationView: ...
