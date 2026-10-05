from datetime import datetime
from uuid import UUID

from acme.om.notifications.storage import NotificationStorageInterface
from acme.om.notifications.types.notification import Notification
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class NotificationStorageMemoryImpl(MemoryStorageBase, NotificationStorageInterface):
    def __init__(self) -> None:
        super().__init__(None)
        self._notifications: MemoryTable[Notification] = {}

    async def create_notification(self, org_id: UUID, notification: Notification) -> bool:
        async with self._lock:
            return self._insert(self._notifications, org_id, notification, ())

    async def read_notification(self, org_id: UUID, notification_id: UUID) -> Notification | None:
        return self._get(self._notifications, org_id, notification_id)

    async def read_notifications(
        self, org_id: UUID, recipient: UUID, limit: int
    ) -> list[Notification]:
        rows = [n for n in self._rows(self._notifications, org_id) if n.recipient == recipient]
        return sorted(rows, key=lambda n: (n.created_at, n.id), reverse=True)[:limit]

    async def mark_read(
        self, org_id: UUID, recipient: UUID, notification_id: UUID, at: datetime
    ) -> Notification | None:
        async with self._lock:
            held = self._get(self._notifications, org_id, notification_id)
            if held is None or held.recipient != recipient:
                return None
            if held.read_at is None:
                held = held.model_copy(update={"read_at": at})
                self._notifications[held.id] = (org_id, held)
            return held

    async def purge_session(self, org_id: UUID, session_id: UUID, limit: int) -> int:
        async with self._lock:
            ids = [
                row.id
                for org, row in self._notifications.values()
                if org == org_id and row.session_id == session_id
            ][:limit]
            for row_id in ids:
                del self._notifications[row_id]
            return len(ids)

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            ids = [row.id for org, row in self._notifications.values() if org == org_id][:limit]
            for row_id in ids:
                del self._notifications[row_id]
            return len(ids)
