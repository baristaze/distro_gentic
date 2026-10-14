from uuid import UUID

from acme.om.context import TenantContext
from acme.om.park_alerts import ParkAlertsManagerInterface
from acme.services.api.services.park_alerts import ParkAlertsServiceInterface
from acme.services.api.types.common import clamp_limit
from acme.services.api.types.park_alerts import ParkAlertView


class ParkAlertsServiceImpl(ParkAlertsServiceInterface):
    def __init__(self, park_alerts: ParkAlertsManagerInterface) -> None:
        self._park_alerts = park_alerts

    async def get_park_alerts(self, ctx: TenantContext, limit: int) -> list[ParkAlertView]:
        told = await self._park_alerts.get_park_alerts(ctx, clamp_limit(limit))
        return [ParkAlertView.model_validate(n) for n in told]

    async def mark_read(self, ctx: TenantContext, park_alert_id: UUID) -> ParkAlertView:
        marked = await self._park_alerts.mark_read(ctx, park_alert_id)
        return ParkAlertView.model_validate(marked)
