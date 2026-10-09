"""The placement storage contract: each tenant's fair share, and the carry
of a share the release before wrote. The cases named
in `CROSS_TENANT_CASES` are the tenant fence's evidence: each one presents
another tenant's identifier and asserts that nothing is found and nothing
changes."""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.placement.storage import PlacementStorageInterface, ShareToCarry
from acme.om.placement.types.share import FairShare

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {"create_share", "mark_carried", "purge_tenant", "read_share", "write_share"}
)
"""Every method of `PlacementStorageInterface` that takes a tenant has a case
in this module that presents another tenant's."""

WrittenBefore = Callable[[UUID, FairShare, int], Awaitable[None]]
"""Lands a tenant's share as the release before wrote it, with the
concurrency it held."""


def make_share(*, plan_tier: str = "standard", own_lane: bool = False) -> FairShare:
    now = utcnow()
    actor = new_id()
    return FairShare(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        plan_tier=plan_tier,
        own_lane=own_lane,
    )


class PlacementStorageContract:
    @pytest.fixture
    def storage(self) -> PlacementStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_round_trip(self, storage: PlacementStorageInterface) -> None:
        org = new_id()
        assert await storage.read_share(org) is None
        share = make_share().model_copy(update={"own_lane": True})
        assert await storage.create_share(org, share)
        assert await storage.read_share(org) == share

    async def test_create_reports_an_existing_id_and_changes_nothing(
        self, storage: PlacementStorageInterface
    ) -> None:
        org = new_id()
        share = make_share()
        assert await storage.create_share(org, share)
        assert not await storage.create_share(org, share.model_copy(update={"plan_tier": "pro"}))
        assert await storage.read_share(org) == share

    async def test_a_tenant_holds_one_share(self, storage: PlacementStorageInterface) -> None:
        org = new_id()
        first = make_share()
        assert await storage.create_share(org, first)
        with pytest.raises(UniqueKeyTaken):
            await storage.create_share(org, make_share(plan_tier="pro"))
        assert await storage.read_share(org) == first

    async def test_create_share_under_another_tenant_is_not_read_here(
        self, storage: PlacementStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        share = make_share()
        assert await storage.create_share(org_a, share)
        assert not await storage.create_share(org_b, share)
        assert await storage.read_share(org_b) is None

    async def test_read_share_of_another_tenant_finds_nothing(
        self, storage: PlacementStorageInterface
    ) -> None:
        assert await storage.create_share(new_id(), make_share())
        assert await storage.read_share(new_id()) is None

    async def test_write_share_is_a_compare_and_set(
        self, storage: PlacementStorageInterface
    ) -> None:
        org = new_id()
        share = make_share()
        assert await storage.create_share(org, share)
        moved = share.model_copy(update={"plan_tier": "pro", "own_lane": True, "version": 2})
        await storage.write_share(org, moved, 1)
        assert await storage.read_share(org) == moved
        with pytest.raises(PreconditionFailed):
            await storage.write_share(org, moved.model_copy(update={"version": 3}), 1)
        assert await storage.read_share(org) == moved

    async def test_write_share_of_another_tenant_changes_nothing(
        self, storage: PlacementStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        share = make_share()
        assert await storage.create_share(org_a, share)
        with pytest.raises(PreconditionFailed):
            await storage.write_share(org_b, share.model_copy(update={"version": 2}), 1)
        assert await storage.read_share(org_a) == share

    async def test_purge_tenant_takes_the_tenants_share_and_no_other(
        self, storage: PlacementStorageInterface
    ) -> None:
        gone, kept = new_id(), new_id()
        stays = make_share()
        assert await storage.create_share(gone, make_share())
        assert await storage.create_share(kept, stays)
        assert await storage.purge_tenant(gone, 10) == 1
        assert await storage.purge_tenant(gone, 10) == 0
        assert await storage.read_share(gone) is None
        assert await storage.read_share(kept) == stays

    # A share the release before wrote, which each concrete class writes as
    # that release did: with its concurrency, and not carried.

    @pytest.fixture
    def written_before(self) -> WrittenBefore:
        raise NotImplementedError("the concrete test class writes as the release before")

    async def test_a_share_written_before_is_read_to_carry_until_it_is_marked(
        self, storage: PlacementStorageInterface, written_before: WrittenBefore
    ) -> None:
        org_a, org_b = new_id(), new_id()
        before = make_share(plan_tier="pro")
        await written_before(org_a, before, 3)
        assert await storage.create_share(org_b, make_share()), "this release's own"
        assert await storage.read_uncarried(10) == [
            ShareToCarry(org_id=org_a, share=before, concurrency=3)
        ]
        assert await storage.read_share(org_a) == before
        assert await storage.mark_carried(org_a, before.id)
        assert not await storage.mark_carried(org_a, before.id), "once"
        assert await storage.read_uncarried(10) == []

    async def test_a_write_leaves_nothing_to_carry(
        self, storage: PlacementStorageInterface, written_before: WrittenBefore
    ) -> None:
        org = new_id()
        before = make_share()
        await written_before(org, before, 3)
        await storage.write_share(org, before.model_copy(update={"version": 2}), 1)
        assert await storage.read_uncarried(10) == []

    async def test_read_uncarried_takes_at_most_its_limit(
        self, storage: PlacementStorageInterface, written_before: WrittenBefore
    ) -> None:
        for _ in range(3):
            await written_before(new_id(), make_share(), 2)
        assert len(await storage.read_uncarried(2)) == 2

    async def test_mark_carried_of_another_tenant_marks_nothing(
        self, storage: PlacementStorageInterface, written_before: WrittenBefore
    ) -> None:
        org_a, org_b = new_id(), new_id()
        before = make_share()
        await written_before(org_a, before, 3)
        assert not await storage.mark_carried(org_b, before.id)
        assert [row.share.id for row in await storage.read_uncarried(10)] == [before.id]
