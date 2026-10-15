"""The park alert storage contract: who was told what waits on them. The
cases named in `CROSS_TENANT_CASES` are the tenant fence's evidence: each
one presents another tenant's identifier and asserts that nothing is found
and nothing changes."""

from datetime import timedelta
from uuid import UUID

from acme.om.agent_steps.types.header import ParkReason
from acme.om.base import new_id, utcnow
from acme.om.park_alerts.storage import ParkAlertStorageInterface
from acme.om.park_alerts.types.park_alert import PORTAL, ParkAlert

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_park_alert",
        "read_park_alert",
        "read_park_alerts",
        "mark_read",
        "purge_agent_session",
        "purge_tenant",
    }
)
"""Every method of `ParkAlertStorageInterface` that takes a tenant has a
case in this module that presents another tenant's."""


def make_park_alert(recipient: UUID, minutes: int = 0) -> ParkAlert:
    return ParkAlert(
        id=new_id(),
        created_at=utcnow() + timedelta(minutes=minutes),
        recipient=recipient,
        agent_session_id=new_id(),
        park_step=new_id(),
        reason=ParkReason.PERSON,
        unlock="approval",
        action="decide_call",
        link="/v1/agent-sessions/x/calls/3/decision",
        channel=PORTAL,
        text="the records: a call to lookup waits for your decision.",
    )


class ParkAlertStorageContract:
    async def test_a_park_alert_reads_back_whole_and_once(
        self, storage: ParkAlertStorageInterface
    ) -> None:
        org = new_id()
        park_alert = make_park_alert(new_id())
        assert await storage.create_park_alert(org, park_alert)
        assert not await storage.create_park_alert(org, park_alert)
        assert await storage.read_park_alert(org, park_alert.id) == park_alert

    async def test_a_recipients_park_alerts_are_newest_first(
        self, storage: ParkAlertStorageInterface
    ) -> None:
        org, ann = new_id(), new_id()
        older, newer = make_park_alert(ann), make_park_alert(ann, minutes=1)
        for park_alert in (older, newer, make_park_alert(new_id())):
            await storage.create_park_alert(org, park_alert)
        assert await storage.read_park_alerts(org, ann, 10) == [newer, older]
        assert await storage.read_park_alerts(org, ann, 1) == [newer]

    async def test_another_tenant_finds_and_changes_nothing(
        self, storage: ParkAlertStorageInterface
    ) -> None:
        org, other, ann = new_id(), new_id(), new_id()
        park_alert = make_park_alert(ann)
        await storage.create_park_alert(org, park_alert)
        assert await storage.read_park_alert(other, park_alert.id) is None
        assert await storage.read_park_alerts(other, ann, 10) == []
        assert not await storage.create_park_alert(other, park_alert)
        assert await storage.read_park_alert(other, park_alert.id) is None

    async def test_a_recipient_marks_their_own_read_once(
        self, storage: ParkAlertStorageInterface
    ) -> None:
        org, ann = new_id(), new_id()
        park_alert = make_park_alert(ann)
        await storage.create_park_alert(org, park_alert)
        first, later = utcnow(), utcnow() + timedelta(minutes=1)
        marked = await storage.mark_read(org, ann, park_alert.id, first)
        assert marked == park_alert.model_copy(update={"read_at": first})
        assert await storage.mark_read(org, ann, park_alert.id, later) == marked
        assert await storage.read_park_alert(org, park_alert.id) == marked

    async def test_mark_read_by_another_recipient_or_tenant_changes_nothing(
        self, storage: ParkAlertStorageInterface
    ) -> None:
        org, other, ann = new_id(), new_id(), new_id()
        park_alert = make_park_alert(ann)
        await storage.create_park_alert(org, park_alert)
        assert await storage.mark_read(org, new_id(), park_alert.id, utcnow()) is None
        assert await storage.mark_read(other, ann, park_alert.id, utcnow()) is None
        assert await storage.read_park_alert(org, park_alert.id) == park_alert

    async def test_purge_tenant_takes_its_rows_and_no_other_tenants(
        self, storage: ParkAlertStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        await storage.create_park_alert(org_a, make_park_alert(new_id()))
        kept = make_park_alert(new_id())
        await storage.create_park_alert(org_b, kept)
        assert await storage.purge_tenant(org_a, 10) == 1
        assert await storage.purge_tenant(org_a, 10) == 0
        assert await storage.read_park_alert(org_b, kept.id) == kept

    async def test_purge_session_takes_that_sessions_rows_alone_in_batches(
        self, storage: ParkAlertStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        gone = make_park_alert(new_id())
        also = gone.model_copy(update={"id": new_id(), "recipient": new_id()})
        kept = make_park_alert(new_id())
        for park_alert in (gone, also, kept):
            await storage.create_park_alert(org, park_alert)
        assert await storage.purge_agent_session(other, gone.agent_session_id, 10) == 0
        assert await storage.purge_agent_session(org, gone.agent_session_id, 1) == 1
        assert await storage.purge_agent_session(org, gone.agent_session_id, 10) == 1
        assert await storage.purge_agent_session(org, gone.agent_session_id, 10) == 0
        assert await storage.read_park_alert(org, gone.id) is None
        assert await storage.read_park_alert(org, kept.id) == kept
