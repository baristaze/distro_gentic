"""The caller's own park alerts: what waits on them, newest first, and a
mark that one is read. Nobody reads or marks another person's."""

from uuid import UUID

from fastapi import APIRouter

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.resolve import ParkAlertsService
from acme.services.api.types.common import LIMIT_DEFAULT
from acme.services.api.types.park_alerts import ParkAlertView

router = APIRouter(prefix="/park-alerts", tags=["park_alerts"])


@router.get("", response_model=list[ParkAlertView])
async def list_park_alerts(
    ctx: Ctx, park_alerts: ParkAlertsService, limit: int = LIMIT_DEFAULT
) -> list[ParkAlertView]:
    return await park_alerts.get_park_alerts(ctx, limit)


@router.post("/{park_alert_id}/read", response_model=ParkAlertView)
async def mark_read(ctx: Ctx, park_alerts: ParkAlertsService, park_alert_id: UUID) -> ParkAlertView:
    """The park alert marked read; the first mark holds."""
    return await park_alerts.mark_read(ctx, park_alert_id)
