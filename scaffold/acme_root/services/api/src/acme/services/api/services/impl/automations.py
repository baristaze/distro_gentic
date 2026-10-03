from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.om.automations import AutomationsManagerInterface
from acme.om.automations.types.automation import Automation
from acme.om.base import utcnow
from acme.om.context import TenantContext
from acme.services.api.services.automations import AutomationsServiceInterface
from acme.services.api.services.impl.built import built
from acme.services.api.types.automations import (
    AutomationPrincipalView,
    AutomationRequest,
    AutomationView,
    GrantRequest,
)


class AutomationsServiceImpl(AutomationsServiceInterface):
    def __init__(
        self, automations: AutomationsManagerInterface, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._automations = automations
        self._clock = clock

    async def get_principal(self, ctx: TenantContext) -> AutomationPrincipalView:
        return AutomationPrincipalView.model_validate(await self._automations.get_principal(ctx))

    async def grant_principal(
        self, ctx: TenantContext, body: GrantRequest
    ) -> AutomationPrincipalView:
        granted = await self._automations.grant_principal(ctx, body.role)
        return AutomationPrincipalView.model_validate(granted)

    async def create_automation(
        self, ctx: TenantContext, body: AutomationRequest, automation_id: UUID
    ) -> AutomationView:
        made = await self._automations.create_automation(ctx, self._built(ctx, body, automation_id))
        return AutomationView.model_validate(made)

    async def list_automations(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> list[AutomationView]:
        found = await self._automations.list_automations(ctx, after, limit)
        return [AutomationView.model_validate(automation) for automation in found]

    async def get_automation(self, ctx: TenantContext, automation_id: UUID) -> AutomationView:
        found = await self._automations.get_automation(ctx, automation_id)
        return AutomationView.model_validate(found)

    async def update_automation(
        self, ctx: TenantContext, automation_id: UUID, body: AutomationRequest
    ) -> AutomationView:
        edited = await self._automations.update_automation(
            ctx, automation_id, self._built(ctx, body, automation_id)
        )
        return AutomationView.model_validate(edited)

    def _built(
        self, ctx: TenantContext, body: AutomationRequest, automation_id: UUID
    ) -> Automation:
        """The automation as the body writes it; a field it leaves out takes
        the object model's default. Its provenance is the manager's: the
        create sets it, and an edit keeps the stored one."""
        now = self._clock()
        return built(
            Automation,
            {
                **body.model_dump(exclude_none=True),
                "id": automation_id,
                "created_at": now,
                "updated_at": now,
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
            },
        )
