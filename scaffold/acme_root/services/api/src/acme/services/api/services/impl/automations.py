from acme.om.automations import AutomationsManagerInterface
from acme.om.context import TenantContext
from acme.services.api.services.automations import AutomationsServiceInterface
from acme.services.api.types.automations import AutomationPrincipalView, GrantRequest


class AutomationsServiceImpl(AutomationsServiceInterface):
    def __init__(self, automations: AutomationsManagerInterface) -> None:
        self._automations = automations

    async def get_principal(self, ctx: TenantContext) -> AutomationPrincipalView:
        return AutomationPrincipalView.model_validate(await self._automations.get_principal(ctx))

    async def grant_principal(
        self, ctx: TenantContext, body: GrantRequest
    ) -> AutomationPrincipalView:
        granted = await self._automations.grant_principal(ctx, body.role)
        return AutomationPrincipalView.model_validate(granted)
