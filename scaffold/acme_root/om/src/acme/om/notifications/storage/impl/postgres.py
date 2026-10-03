from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update

from acme.om.notifications.storage import NotificationStorageInterface
from acme.om.notifications.storage.tables.notifications import Notifications
from acme.om.notifications.types.notification import Notification
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model


class NotificationStoragePostgresImpl(PgStorageBase, NotificationStorageInterface):
    async def create_notification(self, org_id: UUID, notification: Notification) -> bool:
        return await self._insert(Notifications, org_id, notification)

    async def read_notification(self, org_id: UUID, notification_id: UUID) -> Notification | None:
        stmt = select(Notifications).where(
            Notifications.org_id == org_id, Notifications.id == notification_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Notification)

    async def read_notifications(
        self, org_id: UUID, recipient: UUID, limit: int
    ) -> list[Notification]:
        stmt = (
            select(Notifications)
            .where(Notifications.org_id == org_id, Notifications.recipient == recipient)
            .order_by(Notifications.created_at.desc(), Notifications.id.desc())
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, Notification) for row in rows]

    async def mark_read(
        self, org_id: UUID, recipient: UUID, notification_id: UUID, at: datetime
    ) -> Notification | None:
        # The first mark holds: a row read already keeps its time.
        stmt = (
            update(Notifications)
            .where(
                Notifications.org_id == org_id,
                Notifications.id == notification_id,
                Notifications.recipient == recipient,
                Notifications.read_at.is_(None),
            )
            .values(read_at=at)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()
        held = await self.read_notification(org_id, notification_id)
        return held if held is not None and held.recipient == recipient else None

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        stmt = delete_batch(Notifications, Notifications.org_id == org_id, limit=limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            gone = deleted(await session.execute(stmt))
            await session.commit()
            return gone
