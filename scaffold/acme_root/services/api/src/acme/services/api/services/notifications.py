"""The notifications service: the caller's own list of what waits on them,
and a mark that one is read."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.notifications import NotificationView


class NotificationsServiceInterface(ABC):
    @abstractmethod
    async def get_notifications(self, ctx: TenantContext, limit: int) -> list[NotificationView]: ...

    @abstractmethod
    async def mark_read(self, ctx: TenantContext, notification_id: UUID) -> NotificationView: ...
