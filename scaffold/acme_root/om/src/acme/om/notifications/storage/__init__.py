"""Storage of the notifications swimlane: who was told what waits on them,
on which channel. Every operation takes org_id first."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.om.notifications.types.notification import Notification


class NotificationStorageInterface(ABC):
    @abstractmethod
    async def create_notification(self, org_id: UUID, notification: Notification) -> bool:
        """The create; False, with nothing landed, when the id is written
        already."""
        ...

    @abstractmethod
    async def read_notification(
        self, org_id: UUID, notification_id: UUID
    ) -> Notification | None: ...

    @abstractmethod
    async def read_notifications(
        self, org_id: UUID, recipient: UUID, limit: int
    ) -> list[Notification]:
        """A recipient's notifications, newest first."""
        ...

    @abstractmethod
    async def mark_read(
        self, org_id: UUID, recipient: UUID, notification_id: UUID, at: datetime
    ) -> Notification | None:
        """The recipient's notification marked read at `at`, or as marked
        before: the first mark holds. None when the recipient holds no
        notification of that id."""
        ...

    @abstractmethod
    async def purge_session(self, org_id: UUID, session_id: UUID, limit: int) -> int:
        """At most `limit` of the notifications of a session the sweep
        purges; returns how many went."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of a deleted tenant past its retention; returns
        how many went."""
        ...
