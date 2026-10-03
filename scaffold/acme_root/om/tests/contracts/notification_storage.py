"""The notification storage contract: who was told what waits on them. The
cases named in `CROSS_TENANT_CASES` are the tenant fence's evidence: each
one presents another tenant's identifier and asserts that nothing is found
and nothing changes."""

from datetime import timedelta
from uuid import UUID

from acme.om.base import new_id, utcnow
from acme.om.notifications.storage import NotificationStorageInterface
from acme.om.notifications.types.notification import PORTAL, Notification
from acme.om.steps.types.header import ParkReason

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_notification",
        "read_notification",
        "read_notifications",
        "mark_read",
        "purge_tenant",
    }
)
"""Every method of `NotificationStorageInterface` that takes a tenant has a
case in this module that presents another tenant's."""


def make_notification(recipient: UUID, minutes: int = 0) -> Notification:
    return Notification(
        id=new_id(),
        created_at=utcnow() + timedelta(minutes=minutes),
        recipient=recipient,
        session_id=new_id(),
        park_step=new_id(),
        reason=ParkReason.PERSON,
        unlock="approval",
        action="decide_call",
        link="/v1/agent-sessions/x/calls/3/decision",
        channel=PORTAL,
        text="the records: a call to lookup waits for your decision.",
    )


class NotificationStorageContract:
    async def test_a_notification_reads_back_whole_and_once(
        self, storage: NotificationStorageInterface
    ) -> None:
        org = new_id()
        notification = make_notification(new_id())
        assert await storage.create_notification(org, notification)
        assert not await storage.create_notification(org, notification)
        assert await storage.read_notification(org, notification.id) == notification

    async def test_a_recipients_notifications_are_newest_first(
        self, storage: NotificationStorageInterface
    ) -> None:
        org, ann = new_id(), new_id()
        older, newer = make_notification(ann), make_notification(ann, minutes=1)
        for notification in (older, newer, make_notification(new_id())):
            await storage.create_notification(org, notification)
        assert await storage.read_notifications(org, ann, 10) == [newer, older]
        assert await storage.read_notifications(org, ann, 1) == [newer]

    async def test_another_tenant_finds_and_changes_nothing(
        self, storage: NotificationStorageInterface
    ) -> None:
        org, other, ann = new_id(), new_id(), new_id()
        notification = make_notification(ann)
        await storage.create_notification(org, notification)
        assert await storage.read_notification(other, notification.id) is None
        assert await storage.read_notifications(other, ann, 10) == []
        assert not await storage.create_notification(other, notification)
        assert await storage.read_notification(other, notification.id) is None

    async def test_a_recipient_marks_their_own_read_once(
        self, storage: NotificationStorageInterface
    ) -> None:
        org, ann = new_id(), new_id()
        notification = make_notification(ann)
        await storage.create_notification(org, notification)
        first, later = utcnow(), utcnow() + timedelta(minutes=1)
        marked = await storage.mark_read(org, ann, notification.id, first)
        assert marked == notification.model_copy(update={"read_at": first})
        assert await storage.mark_read(org, ann, notification.id, later) == marked
        assert await storage.read_notification(org, notification.id) == marked

    async def test_mark_read_by_another_recipient_or_tenant_changes_nothing(
        self, storage: NotificationStorageInterface
    ) -> None:
        org, other, ann = new_id(), new_id(), new_id()
        notification = make_notification(ann)
        await storage.create_notification(org, notification)
        assert await storage.mark_read(org, new_id(), notification.id, utcnow()) is None
        assert await storage.mark_read(other, ann, notification.id, utcnow()) is None
        assert await storage.read_notification(org, notification.id) == notification

    async def test_purge_tenant_takes_its_rows_and_no_other_tenants(
        self, storage: NotificationStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        await storage.create_notification(org_a, make_notification(new_id()))
        kept = make_notification(new_id())
        await storage.create_notification(org_b, kept)
        assert await storage.purge_tenant(org_a, 10) == 1
        assert await storage.purge_tenant(org_a, 10) == 0
        assert await storage.read_notification(org_b, kept.id) == kept
