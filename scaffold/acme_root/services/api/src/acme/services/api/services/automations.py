"""The automations service: a person grants the tenant's automation
principal a role, and reads the grant."""

from abc import ABC, abstractmethod

from acme.om.context import TenantContext
from acme.services.api.types.automations import AutomationPrincipalView, GrantRequest


class AutomationsServiceInterface(ABC):
    @abstractmethod
    async def get_principal(self, ctx: TenantContext) -> AutomationPrincipalView: ...

    @abstractmethod
    async def grant_principal(
        self, ctx: TenantContext, body: GrantRequest
    ) -> AutomationPrincipalView: ...
