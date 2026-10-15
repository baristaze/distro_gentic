"""The contract every cloud pool storage meets: a VM is found by its
key until the key is spent, by its name, by the session it serves, and by
its tenant, and every VM page by page; a warm VM is claimed once,
and only once it started, at the egress asked, bound from the claim; a
VM started again keeps when it first ran; the warm VMs a sweep
writes never pass the count; and an erasure is asked once per session until
it is done. Its rows are the platform's, so it takes no tenant first and
names no cross-tenant case; the two reads by tenant hold to it by their
predicate, and another tenant's finds nothing."""

import secrets
from datetime import timedelta
from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.types.erasure import PoolErasure
from acme.om.cloud_pool.types.vm import PoolVm
from acme.om.exceptions import UniqueKeyTaken

INTERFACE = CloudPoolStorageInterface
"""The storage interface whose cross-tenant cases this suite holds."""

CROSS_TENANT_CASES: frozenset[str] = frozenset()
"""`CloudPoolStorageInterface` takes no tenant first: its rows are the
platform's."""


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
        tenant, session, pool, person = new_id(), new_id(), new_id(), new_id()
        at = utcnow() + timedelta(minutes=30)
        assert await storage.claim_warm(tenant, session, pool, person, True, at) is None
        claimed = await storage.claim_warm(tenant, session, pool, person, False, at)
        assert claimed is not None and claimed.id == closed.id
        assert (claimed.tenant_id, claimed.agent_session_id, claimed.pool_id, claimed.bound_by) == (
            tenant,
            session,
            pool,
            person,
        )
        assert claimed.bound_at == at and claimed.started_at == closed.started_at
        assert await storage.read_vm(closed.id) == claimed
        assert await storage.claim_warm(tenant, new_id(), pool, person, False, at) is None
        assert await storage.read_of_session(tenant, session) == claimed
        assert await storage.read_of_session(new_id(), session) is None
        assert await storage.read_of_tenant(tenant, 10) == [claimed]

    async def test_the_warm_vms_written_never_pass_the_count(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        await storage.create_vm(make_vm())
        await storage.create_vm(make_vm(tenant_id=new_id(), agent_session_id=new_id()))
        made = [make_vm(started=False) for _ in range(3)]
        assert await storage.reserve_warm(2, made) == 1, "one stands warm already"
        assert await storage.read_vm(made[0].id) == made[0]
        assert await storage.read_vm(made[1].id) is None
        assert await storage.reserve_warm(2, [make_vm(started=False)]) == 0
        assert len(await storage.read_vms(10)) == 3

    async def test_a_vm_started_again_takes_a_new_key_and_its_host_anew(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        vm = make_vm(tenant_id=new_id(), agent_session_id=new_id())
        await storage.create_vm(vm)
        host, at = new_id(), utcnow()
        await storage.mark_enrolled(vm.id, host)
        await storage.mark_sealed(vm.id, at)
        snapshot = new_id()
        later = at + timedelta(hours=2)
        again = await storage.rekey(vm.id, "a new digest", snapshot, later)
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
        assert await storage.rekey(new_id(), "none", None, later) is None

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

    async def test_an_erasure_is_asked_once_per_session_until_it_is_done(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        tenant, session = new_id(), new_id()
        now = utcnow()
        first = PoolErasure(id=new_id(), created_at=now, tenant_id=tenant, agent_session_id=session)
        assert await storage.ask_erase(first) == first
        assert await storage.ask_erase(first.model_copy(update={"id": new_id()})) == first
        other = PoolErasure(
            id=new_id(),
            created_at=now + timedelta(seconds=1),
            tenant_id=tenant,
            agent_session_id=new_id(),
        )
        await storage.ask_erase(other)
        assert await storage.read_erasures(10) == [first, other]
        assert await storage.read_erasures(1) == [first]
        await storage.delete_erasure(first.id)
        assert await storage.read_erasures(10) == [other]
