"""The work storage contract's cases for the methods the platform adds to
it. Each of those that takes a tenant is named in `CROSS_TENANT_CASES` of
`contracts.work_storage`, and its case here presents another tenant's."""

from datetime import timedelta
from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.work.storage import InsertOutcome, WorkStorageInterface
from acme.om.work.types.work_item import WorkItem, WorkKind, WorkStatus
from contracts.work_storage import LEASE, make_item


class PlatformWorkStorageContract:
    @pytest.fixture
    def storage(self) -> WorkStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    @pytest.fixture
    def lane(self) -> str:
        return f"q-{new_id().hex[-12:]}"  # the random tail; the head is the millisecond

    async def test_write_if_queued_is_conditional_on_no_worker_holding_the_item(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org, other_org = new_id(), new_id()
        item = make_item(lane=lane)
        await storage.create_item(org, item)
        ended = item.model_copy(update={"status": WorkStatus.DONE, "last_error": "not wanted"})
        assert await storage.write_item_if_queued(other_org, ended) is None
        assert await storage.read_item(org, item.id) == item
        assert await storage.write_item_if_queued(org, ended) == ended
        assert await storage.read_item(org, item.id) == ended
        assert await storage.write_item_if_queued(org, ended) is None, "ended once"
        assert await storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE) is None
        taken = make_item(lane=lane)
        await storage.create_item(org, taken)
        claimed = await storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE)
        assert claimed is not None and claimed[1].id == taken.id
        late = claimed[1].model_copy(update={"status": WorkStatus.DONE})
        assert await storage.write_item_if_queued(org, late) is None, "a claim lands first"
        assert await storage.read_item(org, taken.id) == claimed[1]
        assert await storage.write_item_if_queued(org, make_item(lane=lane)) is None, "unknown"

    async def test_the_claims_ahead_are_live_of_the_kind_before_it_on_its_lane_alone(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org, now = new_id(), utcnow()

        def claimed(
            seconds_ago: int, *, on: str = lane, kind: WorkKind = WorkKind.LOOP, live: bool = True
        ) -> WorkItem:
            item = make_item(lane=on).model_copy(
                update={
                    "kind": kind,
                    "available_at": now - timedelta(seconds=seconds_ago),
                    "status": WorkStatus.CLAIMED,
                    "claimed_by": "runner",
                    "claim_token": new_id(),
                    "lease_expires_at": now + (LEASE if live else -LEASE),
                }
            )
            return item

        mine = claimed(2)
        ahead = claimed(3)
        behind = claimed(1)
        elsewhere = claimed(0, on=lane + "-other")
        lapsed = claimed(4, live=False)
        another_kind = claimed(5, kind=WorkKind.NOOP)
        queued = claimed(6).model_copy(
            update={
                "status": WorkStatus.QUEUED,
                "claimed_by": None,
                "claim_token": None,
                "lease_expires_at": None,
            }
        )
        for item in (mine, ahead, behind, elsewhere, lapsed, another_kind, queued):
            assert await storage.create_item(org, item) is InsertOutcome.INSERTED
        assert await storage.count_claimed_ahead(org, mine, now) == 1, "ahead, not elsewhere"
        assert await storage.count_claimed_ahead(org, behind, now) == 2
        assert await storage.count_claimed_ahead(org, ahead, now) == 0
        assert await storage.count_claimed_ahead(org, elsewhere, now) == 0, "its own lane alone"

    async def test_count_claimed_ahead_of_another_tenant_counts_none(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org, other_org, now = new_id(), new_id(), utcnow()
        claim = {
            "kind": WorkKind.LOOP,
            "status": WorkStatus.CLAIMED,
            "claimed_by": "runner",
            "lease_expires_at": now + LEASE,
        }
        ahead = make_item(lane=lane).model_copy(
            update={**claim, "claim_token": new_id(), "available_at": now - LEASE}
        )
        mine = make_item(lane=lane).model_copy(update={**claim, "claim_token": new_id()})
        await storage.create_item(org, ahead)
        await storage.create_item(org, mine)
        assert await storage.count_claimed_ahead(org, mine, now) == 1
        assert await storage.count_claimed_ahead(other_org, mine, now) == 0

    async def test_an_open_item_is_one_of_its_kind_on_its_target_queued_or_claimed(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org, other_org, now = new_id(), new_id(), utcnow()
        waiting, running, settled = new_id(), new_id(), new_id()

        def loop_on(target: UUID, status: WorkStatus) -> WorkItem:
            return make_item(lane=lane).model_copy(
                update={"kind": WorkKind.LOOP, "target_id": target, "status": status}
            )

        claimed = loop_on(running, WorkStatus.CLAIMED).model_copy(
            update={"claimed_by": "runner", "claim_token": new_id(), "lease_expires_at": now}
        )
        for item in (
            loop_on(waiting, WorkStatus.QUEUED),
            claimed,
            loop_on(settled, WorkStatus.DONE),
            loop_on(settled, WorkStatus.FAILED),
            make_item(lane=lane).model_copy(update={"target_id": settled}),
        ):
            assert await storage.create_item(org, item) is InsertOutcome.INSERTED
        assert await storage.has_open_item(org, WorkKind.LOOP, waiting)
        assert await storage.has_open_item(org, WorkKind.LOOP, running), "a lapsed lease too"
        assert not await storage.has_open_item(org, WorkKind.LOOP, settled), "done, failed, a noop"
        assert not await storage.has_open_item(org, WorkKind.LOOP, new_id())
        assert not await storage.has_open_item(other_org, WorkKind.LOOP, waiting)

    async def test_the_lanes_depth_counts_what_is_ready_on_each_lane_under_a_prefix(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        """The depth gauge's read: every tenant's ready items, by lane, on the
        lanes that start with the prefix; an item not yet ready, a claimed
        one, and a lane outside the prefix are not counted."""
        org, other = new_id(), new_id()
        hour = timedelta(hours=1)
        for owner, item in (
            (org, make_item(lane=f"{lane}:a")),
            (other, make_item(lane=f"{lane}:a")),
            (org, make_item(lane=f"{lane}:b", available_in=-hour)),
            (org, make_item(lane=f"{lane}:b", available_in=hour)),
            (org, make_item(lane=f"x{lane}:a")),
            (
                org,
                make_item(lane=f"{lane}:b").model_copy(
                    update={"status": WorkStatus.CLAIMED, "lease_expires_at": utcnow() + LEASE}
                ),
            ),
        ):
            await storage.create_item(owner, item)
        depth = await storage.count_ready_by_lane(f"{lane}:", utcnow())
        assert depth == {f"{lane}:a": 2, f"{lane}:b": 1}
        assert await storage.count_ready_by_lane(f"{lane}%", utcnow()) == {}

    async def test_the_ready_items_ahead_are_counted_in_the_claim_order_of_one_lane(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        """An item's place in line counts every tenant's ready items before
        it on its lane, and nothing after it, on another lane, or not ready."""
        org, other = new_id(), new_id()
        hour = timedelta(hours=1)
        first = make_item(lane=lane, available_in=-2 * hour)
        second = make_item(lane=lane, available_in=-hour)
        mine = make_item(lane=lane, available_in=-hour / 2)
        await storage.create_item(other, first)
        await storage.create_item(org, second)
        await storage.create_item(org, mine)
        await storage.create_item(org, make_item(lane=lane))
        await storage.create_item(org, make_item(lane=f"{lane}-b", available_in=-3 * hour))
        assert await storage.count_ready_ahead(mine, utcnow()) == 2
        assert await storage.count_ready_ahead(first, utcnow()) == 0

    async def test_the_ready_items_on_a_tenants_lanes_are_counted_by_lane_and_kind(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org = new_id()
        loop = make_item(lane=lane).model_copy(update={"kind": WorkKind.LOOP})
        await storage.create_item(org, loop)
        await storage.create_item(org, make_item(lane=lane))
        await storage.create_item(org, make_item(lane=lane))
        await storage.create_item(org, make_item(lane=f"{lane}-b", available_in=timedelta(hours=1)))
        found = await storage.count_ready_on_lanes(org, [lane, f"{lane}-b"], utcnow())
        assert found == {(lane, WorkKind.NOOP): 2, (lane, WorkKind.LOOP): 1}
        assert await storage.count_ready_on_lanes(org, [], utcnow()) == {}

    async def test_count_ready_on_lanes_of_another_tenant_finds_nothing(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        await storage.create_item(new_id(), make_item(lane=lane))
        assert await storage.count_ready_on_lanes(new_id(), [lane], utcnow()) == {}

    async def test_the_latest_item_for_a_target_is_the_one_made_last(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org, target = new_id(), new_id()
        hour = timedelta(hours=1)
        older = make_item(lane=lane).model_copy(
            update={"target_id": target, "created_at": utcnow() - hour, "kind": WorkKind.LOOP}
        )
        newer = make_item(lane=lane).model_copy(update={"target_id": target, "kind": WorkKind.LOOP})
        other_kind = make_item(lane=lane).model_copy(update={"target_id": target})
        for item in (older, newer, other_kind):
            await storage.create_item(org, item)
        assert await storage.read_latest_for_target(org, WorkKind.LOOP, target) == newer
        assert await storage.read_latest_for_target(org, WorkKind.LOOP, new_id()) is None

    async def test_read_latest_for_target_of_another_tenant_finds_nothing(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        target = new_id()
        item = make_item(lane=lane).model_copy(update={"target_id": target})
        await storage.create_item(new_id(), item)
        assert await storage.read_latest_for_target(new_id(), WorkKind.NOOP, target) is None

    async def test_end_open_on_lane_ends_its_queued_and_held_items_alone(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        """A revoked host's lane: its queued and claimed items end as done,
        their claim cleared, in batches; a settled item, another lane's, and
        another tenant's stay as they were."""
        org, other = new_id(), new_id()
        queued, held = make_item(lane=lane), make_item(lane=lane)
        settled = make_item(lane=lane).model_copy(update={"status": WorkStatus.FAILED})
        elsewhere = make_item(lane=f"{lane}-other")
        for item in (queued, held, settled, elsewhere):
            await storage.create_item(org, item)
        theirs = make_item(lane=lane)
        await storage.create_item(other, theirs)
        claimed = await storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE)
        assert claimed is not None and claimed[1].id in {queued.id, held.id}
        now = utcnow()
        assert await storage.end_open_on_lane(new_id(), lane, "gone", now, 10) == []
        first = await storage.end_open_on_lane(org, lane, "gone", now, 1)
        second = await storage.end_open_on_lane(org, lane, "gone", now, 10)
        assert await storage.end_open_on_lane(org, lane, "gone", now, 10) == []
        assert {item.id for item in (*first, *second)} == {queued.id, held.id}
        for item in (*first, *second):
            stored = await storage.read_item(org, item.id)
            assert stored is not None and stored.status is WorkStatus.DONE
            assert (stored.last_error, stored.claim_token, stored.lease_expires_at) == (
                "gone",
                None,
                None,
            )
        for tenant, kept in ((org, settled), (org, elsewhere), (other, theirs)):
            stored = await storage.read_item(tenant, kept.id)
            assert stored is not None and stored.status is kept.status

    async def test_end_open_for_target_ends_that_targets_open_items_alone(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org, other = new_id(), new_id()
        mine = make_item(lane=lane)
        also = make_item(lane=lane).model_copy(update={"target_id": mine.target_id})
        kept = make_item(lane=lane)
        for item in (mine, also, kept):
            await storage.create_item(org, item)
        target = mine.target_id
        now = utcnow()
        assert await storage.end_open_for_target(other, WorkKind.NOOP, target, "x", now, 10) == []
        assert await storage.end_open_for_target(org, WorkKind.EXEC, target, "x", now, 10) == []
        ended = await storage.end_open_for_target(org, WorkKind.NOOP, target, "x", now, 10)
        assert {item.id for item in ended} == {mine.id, also.id}
        stored = await storage.read_item(org, kept.id)
        assert stored is not None and stored.status is WorkStatus.QUEUED
