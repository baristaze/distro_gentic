"""The contract every cloud pool storage meets: a VM is found by its
key until the key is spent, by its name, by the session it serves, and by
its tenant, and every VM page by page; a claim holds its tenant's maximum
and the pool's, and binds a warm VM once, and only once it started, at
the egress asked, from the claim; at the pool's maximum, a claim that
takes no warm VM takes an idle one's place; a VM a claim writes reads
back cold, and one it binds warm or starts again does not; a warm VM's
row is taken only while no session claimed it; a VM started again keeps
when it first ran; the warm VMs a sweep writes never pass the count or
the maximum, each kind counted apart, running and started to sleep; a
claim takes a warm VM that runs before one asleep, hands the one asleep
its own key digest, and takes none started to sleep that sleeps not yet;
a VM started to sleep has its key ended once, while no session claimed
it; a session's archives are one row, moved forward as it keeps more and
read oldest first until they go; and the pool's limits and a tenant's own
maximum are written over the version read. Its VMs are the platform's rows, read by their predicate,
and another tenant's finds nothing; a tenant's own maximum is that
tenant's, and its cases present another tenant's."""

import secrets
from datetime import timedelta
from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.types.archive import PoolArchive
from acme.om.cloud_pool.types.limits import Full, PoolLimits, TenantPoolLimit
from acme.om.cloud_pool.types.vm import PoolClaim, PoolVm
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken

INTERFACE = CloudPoolStorageInterface
"""The storage interface whose cross-tenant cases this suite holds."""

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {"read_tenant_limit", "write_tenant_limit", "delete_tenant_limit"}
)
"""A tenant's own maximum is the one row `CloudPoolStorageInterface` keys by
its tenant; the VMs and the pool's limits are the platform's."""

FAR = 1000
"""A maximum no case reaches."""


def make_limit(most: int, version: int = 1) -> TenantPoolLimit:
    now = utcnow()
    return TenantPoolLimit(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=new_id(),
        updated_by=new_id(),
        most=most,
        version=version,
    )


def make_vm(
    *,
    egress_open: bool = True,
    tenant_id: UUID | None = None,
    agent_session_id: UUID | None = None,
    started: bool = True,
) -> PoolVm:
    now = utcnow()
    return PoolVm(
        id=new_id(),
        created_at=now,
        name=f"acme-vm-p{secrets.token_hex(8)}",
        egress_open=egress_open,
        tenant_id=tenant_id,
        agent_session_id=agent_session_id,
        pool_id=None if agent_session_id is None else new_id(),
        bound_by=None if agent_session_id is None else new_id(),
        key_digest=new_id().hex,
        started_at=now if started else None,
    )


class CloudPoolStorageContract:
    @pytest.fixture
    def storage(self) -> CloudPoolStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_a_vm_round_trips_and_is_found_by_its_key(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        vm = make_vm()
        await storage.create_vm(vm)
        assert await storage.read_vm(vm.id) == vm
        assert vm.key_digest is not None
        assert await storage.read_by_key(vm.key_digest) == vm
        assert await storage.read_by_key("another digest") is None

    async def test_a_name_and_a_key_are_each_one_vms(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        vm = make_vm()
        await storage.create_vm(vm)
        with pytest.raises(UniqueKeyTaken):
            await storage.create_vm(make_vm().model_copy(update={"name": vm.name}))
        with pytest.raises(UniqueKeyTaken):
            await storage.create_vm(make_vm().model_copy(update={"key_digest": vm.key_digest}))

    async def test_a_vm_a_claim_writes_reads_back_cold_and_one_bound_warm_or_restarted_not(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        warm = make_vm()
        await storage.create_vm(warm)
        now = utcnow()
        asked = make_vm(tenant_id=new_id(), agent_session_id=new_id(), started=False)
        asked = asked.model_copy(update={"created_at": now, "bound_at": now})
        assert await storage.claim(asked, most=FAR, tenant_most=FAR, warm=False) == PoolClaim(
            vm=asked
        )
        written = await storage.read_vm(asked.id)
        assert written is not None and written.cold, "bound as its row was written"

        claim = make_vm(tenant_id=new_id(), agent_session_id=new_id(), started=False)
        claim = claim.model_copy(update={"bound_at": utcnow(), "restored_from": new_id()})
        bound = await storage.claim(claim, most=FAR, tenant_most=FAR, warm=True)
        assert isinstance(bound, PoolClaim) and bound.vm.id == warm.id
        read = await storage.read_vm(warm.id)
        assert read is not None and not read.cold, "a warm VM is bound at its claim"
        assert read.restored_from == claim.restored_from, "and takes back what the claim asks"

        await storage.rekey(asked.id, new_id().hex, utcnow())
        again = await storage.read_vm(asked.id)
        assert again is not None and not again.cold, "a start again binds it anew"

    async def test_a_key_is_spent_once(self, storage: CloudPoolStorageInterface) -> None:
        vm = make_vm()
        await storage.create_vm(vm)
        assert vm.key_digest is not None
        assert await storage.spend_key(vm.id, vm.key_digest) is True
        assert await storage.spend_key(vm.id, vm.key_digest) is False
        assert await storage.read_by_key(vm.key_digest) is None
        spent = await storage.read_vm(vm.id)
        assert spent is not None and spent.key_digest is None

    async def test_a_warm_vm_is_claimed_once_started_at_its_egress_and_once(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        starting = make_vm(started=False)
        closed = make_vm(egress_open=False)
        await storage.create_vm(starting)
        await storage.create_vm(closed)
        tenant, session, person = new_id(), new_id(), new_id()
        asked = make_vm(
            egress_open=False, tenant_id=tenant, agent_session_id=session, started=False
        )
        asked = asked.model_copy(
            update={"bound_by": person, "bound_at": utcnow() + timedelta(minutes=30)}
        )
        got = await storage.claim(asked, most=FAR, tenant_most=FAR, warm=True)
        assert isinstance(got, PoolClaim) and got.displaced is None
        claimed = got.vm
        assert claimed.id == closed.id
        assert (claimed.tenant_id, claimed.agent_session_id, claimed.pool_id, claimed.bound_by) == (
            tenant,
            session,
            asked.pool_id,
            person,
        )
        assert claimed.bound_at == asked.bound_at and claimed.started_at == closed.started_at
        assert claimed.name == closed.name and claimed.key_digest == closed.key_digest
        assert await storage.read_vm(closed.id) == claimed
        assert await storage.read_vm(asked.id) is None, "a warm one bound, none written"
        again = asked.model_copy(update={"id": new_id(), "agent_session_id": new_id()})
        written = await storage.claim(again, most=FAR, tenant_most=FAR, warm=True)
        assert written == PoolClaim(vm=again), (
            "the warm one starting is not claimed, so its own is written"
        )
        assert await storage.read_of_session(tenant, session) == claimed
        assert await storage.read_of_session(new_id(), session) is None
        assert len(await storage.read_of_tenant(tenant, 10)) == 2

    async def test_a_claim_holds_its_tenants_maximum_and_the_pools(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        tenant = new_id()
        await storage.create_vm(make_vm(tenant_id=tenant, agent_session_id=new_id()))
        warm = make_vm()  # of no tenant
        await storage.create_vm(warm)
        asked = make_vm(tenant_id=tenant, agent_session_id=new_id(), started=False)
        for warm_asked in (True, False):
            assert await storage.claim(asked, most=1, tenant_most=1, warm=warm_asked) is Full.TENANT
        assert await storage.read_vm(asked.id) is None
        assert await storage.read_vm(warm.id) == warm, "nor a warm one bound, nor its place taken"
        late = make_vm(tenant_id=new_id(), agent_session_id=new_id(), started=False)
        bound = await storage.claim(late, most=2, tenant_most=1, warm=True)
        assert isinstance(bound, PoolClaim) and bound.vm.id == warm.id, (
            "a warm one is bound at the maximum: it is counted already"
        )
        theirs = make_vm(tenant_id=new_id(), agent_session_id=new_id(), started=False)
        assert await storage.claim(theirs, most=2, tenant_most=1, warm=False) is Full.POOL
        assert await storage.claim(theirs, most=3, tenant_most=1, warm=False) == PoolClaim(
            vm=theirs
        )
        assert await storage.read_vm(theirs.id) == theirs
        assert len(await storage.read_vms(10)) == 3

    async def test_a_claim_at_the_maximum_that_takes_no_warm_vm_takes_an_idle_ones_place(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        starting = make_vm(started=False)
        first, second = make_vm(egress_open=False), make_vm(egress_open=False)
        for vm in (starting, first, second):
            await storage.create_vm(vm)
        opened = make_vm(tenant_id=new_id(), agent_session_id=new_id(), started=False)
        got = await storage.claim(opened, most=3, tenant_most=FAR, warm=True)
        assert isinstance(got, PoolClaim) and got.vm == opened, "no warm VM of its egress stands"
        assert got.displaced in (first, second)
        assert await storage.read_vm(got.displaced.id) is None, "the idle warm VM's row went"
        assert await storage.read_vm(opened.id) == opened
        left = second if got.displaced == first else first
        restore = make_vm(
            egress_open=False, tenant_id=new_id(), agent_session_id=new_id(), started=False
        )
        assert await storage.claim(restore, most=3, tenant_most=FAR, warm=False) == PoolClaim(
            vm=restore, displaced=left
        ), "a claim that may take no warm VM takes an idle one's place"
        late = make_vm(tenant_id=new_id(), agent_session_id=new_id(), started=False)
        assert await storage.claim(late, most=3, tenant_most=FAR, warm=False) is Full.POOL, (
            "a warm VM still starting is not idle, and keeps its place"
        )
        assert {vm.id for vm in await storage.read_vms(10)} == {starting.id, opened.id, restore.id}

    async def test_the_warm_vms_written_never_pass_the_count_or_the_maximum(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        await storage.create_vm(make_vm())
        await storage.create_vm(make_vm(tenant_id=new_id(), agent_session_id=new_id()))
        made = [make_vm(started=False) for _ in range(3)]
        assert await storage.reserve_warm(2, FAR, made) == 1, "one stands warm already"
        assert await storage.read_vm(made[0].id) == made[0]
        assert await storage.read_vm(made[1].id) is None
        assert await storage.reserve_warm(2, FAR, [make_vm(started=False)]) == 0
        assert len(await storage.read_vms(10)) == 3
        assert await storage.reserve_warm(5, 4, [make_vm(started=False) for _ in range(3)]) == 1
        assert await storage.reserve_warm(5, 4, [make_vm(started=False)]) == 0
        assert len(await storage.read_vms(10)) == 4

    async def test_a_claim_takes_a_warm_vm_that_runs_then_one_asleep_and_none_settling(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        old = utcnow() - timedelta(hours=1)
        settling = make_vm().model_copy(update={"hibernates": True, "created_at": old})
        asleep = make_vm().model_copy(
            update={
                "hibernates": True,
                "hibernated_at": old,
                "key_digest": None,
                "created_at": old + timedelta(seconds=1),
            }
        )
        running = make_vm()
        for vm in (settling, asleep, running):
            await storage.create_vm(vm)

        def asked() -> PoolVm:
            return make_vm(tenant_id=new_id(), agent_session_id=new_id(), started=False)

        first = await storage.claim(asked(), most=FAR, tenant_most=FAR, warm=True)
        assert isinstance(first, PoolClaim) and first.vm.id == running.id, "the one that runs first"
        assert first.vm.key_digest == running.key_digest, "its host holds its key already"
        fresh = asked()
        second = await storage.claim(fresh, most=FAR, tenant_most=FAR, warm=True)
        assert isinstance(second, PoolClaim) and second.vm.id == asleep.id, "then the one asleep"
        assert second.vm.key_digest == fresh.key_digest, "it wakes with the claim's key"
        assert second.vm.agent_session_id == fresh.agent_session_id
        assert await storage.read_by_key(fresh.key_digest or "") == second.vm
        third = asked()
        assert await storage.claim(third, most=FAR, tenant_most=FAR, warm=True) == PoolClaim(
            vm=third
        ), "one started to sleep that sleeps not yet is never claimed"
        assert await storage.read_vm(settling.id) == settling

    async def test_a_vm_started_to_sleep_has_its_key_ended_once_while_no_session_claimed_it(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        sleeper = make_vm().model_copy(update={"hibernates": True})
        claimed = make_vm().model_copy(update={"hibernates": True})
        running = make_vm()
        for vm in (sleeper, claimed, running):
            await storage.create_vm(vm)
        assert sleeper.key_digest is not None and running.key_digest is not None
        assert await storage.take_to_sleep(running.id, running.key_digest) is False, (
            "a warm VM that runs never sleeps"
        )
        assert await storage.take_to_sleep(sleeper.id, "another digest") is False
        assert await storage.take_to_sleep(sleeper.id, sleeper.key_digest) is True
        assert await storage.take_to_sleep(sleeper.id, sleeper.key_digest) is False, "once"
        assert await storage.read_by_key(sleeper.key_digest) is None, "its key enrolls no more"
        at = utcnow()
        await storage.mark_hibernated(sleeper.id, at)
        read = await storage.read_vm(sleeper.id)
        assert read is not None and read.asleep and read.hibernated_at == at

        # A claim binds the other while it settles, as no sweep lets it: its
        # row then names a session, and nothing takes it to sleep.
        bound = claimed.model_copy(
            update={"tenant_id": new_id(), "agent_session_id": new_id(), "pool_id": new_id()}
        )
        await storage.delete_vm(claimed.id)
        await storage.create_vm(bound)
        assert bound.key_digest is not None
        assert await storage.take_to_sleep(bound.id, bound.key_digest) is False
        await storage.mark_hibernated(bound.id, at)
        assert await storage.read_vm(bound.id) == bound, "a session's VM is never marked asleep"

    async def test_the_warm_vms_of_each_kind_are_counted_apart_and_both_within_the_maximum(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        await storage.create_vm(make_vm())  # one that runs

        def sleepers(count: int) -> list[PoolVm]:
            return [
                make_vm(started=False).model_copy(update={"hibernates": True}) for _ in range(count)
            ]

        assert await storage.reserve_warm(2, FAR, sleepers(3), hibernates=True) == 2, (
            "the one that runs is not of their kind"
        )
        assert await storage.reserve_warm(2, FAR, sleepers(1), hibernates=True) == 0
        assert await storage.reserve_warm(1, FAR, [make_vm(started=False)]) == 0, (
            "nor are they of its"
        )
        assert await storage.reserve_warm(5, 4, sleepers(3), hibernates=True) == 1, (
            "a VM asleep or settling holds a place under the maximum"
        )
        assert await storage.reserve_warm(2, 4, [make_vm(started=False)]) == 0
        assert len(await storage.read_vms(10)) == 4

    async def test_a_warm_vms_row_is_taken_only_while_no_session_claimed_it(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        warm, claimed = make_vm(), make_vm()
        await storage.create_vm(warm)
        await storage.create_vm(claimed)
        asked = make_vm(tenant_id=new_id(), agent_session_id=new_id(), started=False)
        got = await storage.claim(asked, most=FAR, tenant_most=FAR, warm=True)
        assert isinstance(got, PoolClaim)
        bound = got.vm
        taken = warm if bound.id == claimed.id else claimed
        assert await storage.take_warm(bound.id) is False, "a session holds it"
        assert await storage.read_vm(bound.id) == bound
        assert await storage.take_warm(taken.id) is True
        assert await storage.read_vm(taken.id) is None
        assert await storage.take_warm(taken.id) is False, "gone"

    async def test_the_pools_limits_are_written_over_the_version_read(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        assert await storage.read_limits() is None
        now = utcnow()
        first = PoolLimits(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=new_id(),
            updated_by=new_id(),
            warm=1,
            most=4,
            tenant_most=2,
        )
        assert await storage.write_limits(first, None) == first
        assert await storage.read_limits() == first
        with pytest.raises(PreconditionFailed):
            await storage.write_limits(first.model_copy(update={"id": new_id()}), None)
        second = first.model_copy(update={"id": new_id(), "most": 8, "version": 2})
        assert await storage.write_limits(second, 1) == second
        with pytest.raises(PreconditionFailed):
            await storage.write_limits(second.model_copy(update={"id": new_id(), "version": 2}), 1)
        assert await storage.read_limits() == second

    async def test_a_tenants_own_maximum_is_written_over_its_version_and_another_finds_none(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        tenant, other = new_id(), new_id()
        assert await storage.read_tenant_limit(tenant) is None
        first = make_limit(3)
        assert await storage.write_tenant_limit(tenant, first, None) == first
        assert await storage.read_tenant_limit(tenant) == first
        assert await storage.read_tenant_limit(other) is None
        with pytest.raises(PreconditionFailed):
            await storage.write_tenant_limit(tenant, make_limit(4), None)
        with pytest.raises(PreconditionFailed):
            await storage.write_tenant_limit(other, first.model_copy(update={"most": 9}), 1)
        assert await storage.read_tenant_limit(other) is None, "another tenant's write lands none"
        second = first.model_copy(update={"most": 5, "version": 2})
        assert await storage.write_tenant_limit(tenant, second, 1) == second
        with pytest.raises(PreconditionFailed):
            await storage.write_tenant_limit(tenant, second, 1)
        assert await storage.delete_tenant_limit(other) is None
        assert await storage.read_tenant_limit(tenant) == second, "another tenant's delete"
        assert await storage.delete_tenant_limit(tenant) == second
        assert await storage.read_tenant_limit(tenant) is None

    async def test_a_vm_started_again_takes_a_new_key_and_its_host_anew(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        snapshot = new_id()
        vm = make_vm(tenant_id=new_id(), agent_session_id=new_id())
        vm = vm.model_copy(update={"restored_from": snapshot})
        await storage.create_vm(vm)
        host, at = new_id(), utcnow()
        await storage.mark_enrolled(vm.id, host)
        await storage.mark_sealed(vm.id, at)
        later = at + timedelta(hours=2)
        again = await storage.rekey(vm.id, "a new digest", later)
        assert again is not None
        assert (again.key_digest, again.restored_from, again.host_id) == (
            "a new digest",
            snapshot,
            None,
        )
        assert again.sealed_at is None and again.bound_at == later
        assert again.started_at == vm.started_at, "it ran on this disk already"
        assert await storage.read_vm(vm.id) == again
        await storage.mark_started(vm.id, later)
        started = await storage.read_vm(vm.id)
        assert started is not None and started.started_at == later
        assert await storage.rekey(new_id(), "none", later) is None

    async def test_another_tenant_finds_no_vm(self, storage: CloudPoolStorageInterface) -> None:
        tenant, session = new_id(), new_id()
        await storage.create_vm(make_vm(tenant_id=tenant, agent_session_id=session))
        assert await storage.read_of_session(new_id(), session) is None
        assert await storage.read_of_tenant(new_id(), 10) == []
        assert len(await storage.read_of_tenant(tenant, 10)) == 1

    async def test_a_deleted_vm_is_gone_and_every_vm_is_read_page_by_page(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        made = [make_vm() for _ in range(5)]
        for vm in made:
            await storage.create_vm(vm)
        pages: list[list[UUID]] = []
        after: UUID | None = None
        while page := await storage.read_vms(2, after):
            pages.append([m.id for m in page])
            after = page[-1].id
        assert [len(page) for page in pages] == [2, 2, 1]
        assert [id_ for page in pages for id_ in page] == sorted(m.id for m in made)
        first = made[0]
        await storage.delete_vm(first.id)
        assert await storage.read_vm(first.id) is None
        assert first.id not in [m.id for m in await storage.read_vms(10)]

    async def test_a_vm_is_found_by_its_name(self, storage: CloudPoolStorageInterface) -> None:
        vm = make_vm()
        await storage.create_vm(vm)
        assert await storage.read_by_name(vm.name) == vm
        assert await storage.read_by_name("acme-vm-pnone") is None

    async def test_a_sessions_archives_are_one_row_moved_forward_and_read_oldest_first(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        tenant, other, now = new_id(), new_id(), utcnow()

        def archive(tenant_id: UUID, days: int) -> PoolArchive:
            return PoolArchive(
                id=new_id(),
                created_at=now,
                tenant_id=tenant_id,
                agent_session_id=new_id(),
                kept_at=now - timedelta(days=days),
            )

        mine, theirs, newer = archive(tenant, 40), archive(other, 35), archive(tenant, 1)
        for kept in (mine, theirs, newer):
            await storage.keep_archive(kept)
        idle = now - timedelta(days=30)
        assert await storage.read_archives(idle, 10) == [mine, theirs]
        assert await storage.read_archives(idle, 1) == [mine]

        # Kept again, or seen active: the one row moves, and keeps its id.
        await storage.keep_archive(mine.model_copy(update={"id": new_id(), "kept_at": now}))
        assert await storage.read_archives(idle, 10) == [theirs]
        moved = await storage.read_archives(now + timedelta(seconds=1), 10)
        assert [
            (a.id, a.kept_at) for a in moved if a.agent_session_id == mine.agent_session_id
        ] == [(mine.id, now)]

        await storage.delete_archive(other, mine.agent_session_id)  # another tenant's: none
        await storage.delete_archive(other, theirs.agent_session_id)
        assert await storage.delete_tenant_archives(tenant) == 2
        assert await storage.read_archives(now + timedelta(days=1), 10) == []
