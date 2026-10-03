"""The caller's own notifications: what waits on them, newest first, and a
mark that one is read. Nobody reads or marks another person's."""

from uuid import UUID

from fastapi import APIRouter

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.resolve import NotificationsService
from acme.services.api.types.common import LIMIT_DEFAULT
from acme.services.api.types.notifications import NotificationView

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationView])
async def list_notifications(
    ctx: Ctx, notifications: NotificationsService, limit: int = LIMIT_DEFAULT
) -> list[NotificationView]:
    return await notifications.get_notifications(ctx, limit)


@router.post("/{notification_id}/read", response_model=NotificationView)
async def mark_read(
    ctx: Ctx, notifications: NotificationsService, notification_id: UUID
) -> NotificationView:
    """The notification marked read; the first mark holds."""
    return await notifications.mark_read(ctx, notification_id)
