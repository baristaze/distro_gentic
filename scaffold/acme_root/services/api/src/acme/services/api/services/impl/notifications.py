from uuid import UUID

from acme.om.context import TenantContext
from acme.om.notifications import NotificationsManagerInterface
from acme.services.api.services.notifications import NotificationsServiceInterface
from acme.services.api.types.common import clamp_limit
from acme.services.api.types.notifications import NotificationView


class NotificationsServiceImpl(NotificationsServiceInterface):
    def __init__(self, notifications: NotificationsManagerInterface) -> None:
        self._notifications = notifications

    async def get_notifications(self, ctx: TenantContext, limit: int) -> list[NotificationView]:
        told = await self._notifications.get_notifications(ctx, clamp_limit(limit))
        return [NotificationView.model_validate(n) for n in told]

    async def mark_read(self, ctx: TenantContext, notification_id: UUID) -> NotificationView:
        marked = await self._notifications.mark_read(ctx, notification_id)
        return NotificationView.model_validate(marked)
