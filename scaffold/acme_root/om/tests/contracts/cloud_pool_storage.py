"""The contract every cloud pool storage meets: a machine is found by its
key until the key is spent, by its name, by the session it serves, and by
its tenant, and every machine page by page; a warm machine is claimed once,
and only once it started, at the egress asked, bound from the claim; a
machine started again keeps when it first ran; the warm machines a sweep
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
from acme.om.cloud_pool.types.machine import PoolVm
from acme.om.exceptions import UniqueKeyTaken

CROSS_TENANT_CASES: frozenset[str] = frozenset()
"""`CloudPoolStorageInterface` takes no tenant first: its rows are the
platform's."""


def make_machine(
    *,
    egress_open: bool = True,
    tenant_id: UUID | None = None,
    session_id: UUID | None = None,
    started: bool = True,
) -> PoolVm:
    now = utcnow()
    return PoolVm(
        id=new_id(),
        created_at=now,
        name=f"acme-vm-p{secrets.token_hex(8)}",
        egress_open=egress_open,
        tenant_id=tenant_id,
        session_id=session_id,
        pool_id=None if session_id is None else new_id(),
        bound_by=None if session_id is None else new_id(),
        key_digest=new_id().hex,
        started_at=now if started else None,
    )


class CloudPoolStorageContract:
    @pytest.fixture
    def storage(self) -> CloudPoolStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_a_machine_round_trips_and_is_found_by_its_key(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        machine = make_machine()
        await storage.create_machine(machine)
        assert await storage.read_machine(machine.id) == machine
        assert machine.key_digest is not None
        assert await storage.read_by_key(machine.key_digest) == machine
        assert await storage.read_by_key("another digest") is None

    async def test_a_name_and_a_key_are_each_one_machines(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        machine = make_machine()
        await storage.create_machine(machine)
        with pytest.raises(UniqueKeyTaken):
            await storage.create_machine(make_machine().model_copy(update={"name": machine.name}))
        with pytest.raises(UniqueKeyTaken):
            await storage.create_machine(
                make_machine().model_copy(update={"key_digest": machine.key_digest})
            )

    async def test_a_key_is_spent_once(self, storage: CloudPoolStorageInterface) -> None:
        machine = make_machine()
        await storage.create_machine(machine)
        assert machine.key_digest is not None
        assert await storage.spend_key(machine.id, machine.key_digest) is True
        assert await storage.spend_key(machine.id, machine.key_digest) is False
        assert await storage.read_by_key(machine.key_digest) is None
        spent = await storage.read_machine(machine.id)
        assert spent is not None and spent.key_digest is None

    async def test_a_warm_machine_is_claimed_once_started_at_its_egress_and_once(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        starting = make_machine(started=False)
        closed = make_machine(egress_open=False)
        await storage.create_machine(starting)
        await storage.create_machine(closed)
        tenant, session, pool, person = new_id(), new_id(), new_id(), new_id()
        at = utcnow() + timedelta(minutes=30)
        assert await storage.claim_warm(tenant, session, pool, person, True, at) is None
        claimed = await storage.claim_warm(tenant, session, pool, person, False, at)
        assert claimed is not None and claimed.id == closed.id
        assert (claimed.tenant_id, claimed.session_id, claimed.pool_id, claimed.bound_by) == (
            tenant,
            session,
            pool,
            person,
        )
        assert claimed.bound_at == at and claimed.started_at == closed.started_at
        assert await storage.read_machine(closed.id) == claimed
        assert await storage.claim_warm(tenant, new_id(), pool, person, False, at) is None
        assert await storage.read_of_session(tenant, session) == claimed
        assert await storage.read_of_session(new_id(), session) is None
        assert await storage.read_of_tenant(tenant, 10) == [claimed]

    async def test_the_warm_machines_written_never_pass_the_count(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        await storage.create_machine(make_machine())
        await storage.create_machine(make_machine(tenant_id=new_id(), session_id=new_id()))
        made = [make_machine(started=False) for _ in range(3)]
        assert await storage.reserve_warm(2, made) == 1, "one stands warm already"
        assert await storage.read_machine(made[0].id) == made[0]
        assert await storage.read_machine(made[1].id) is None
        assert await storage.reserve_warm(2, [make_machine(started=False)]) == 0
        assert len(await storage.read_machines(10)) == 3

    async def test_a_machine_started_again_takes_a_new_key_and_its_host_anew(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        machine = make_machine(tenant_id=new_id(), session_id=new_id())
        await storage.create_machine(machine)
        host, at = new_id(), utcnow()
        await storage.mark_enrolled(machine.id, host)
        await storage.mark_sealed(machine.id, at)
        snapshot = new_id()
        later = at + timedelta(hours=2)
        again = await storage.rekey(machine.id, "a new digest", snapshot, later)
        assert again is not None
        assert (again.key_digest, again.restored_from, again.host_id) == (
            "a new digest",
            snapshot,
            None,
        )
        assert again.sealed_at is None and again.bound_at == later
        assert again.started_at == machine.started_at, "it ran on this disk already"
        assert await storage.read_machine(machine.id) == again
        await storage.mark_started(machine.id, later)
        started = await storage.read_machine(machine.id)
        assert started is not None and started.started_at == later
        assert await storage.rekey(new_id(), "none", None, later) is None

    async def test_another_tenant_finds_no_machine(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        tenant, session = new_id(), new_id()
        await storage.create_machine(make_machine(tenant_id=tenant, session_id=session))
        assert await storage.read_of_session(new_id(), session) is None
        assert await storage.read_of_tenant(new_id(), 10) == []
        assert len(await storage.read_of_tenant(tenant, 10)) == 1

    async def test_a_deleted_machine_is_gone_and_every_machine_is_read_page_by_page(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        made = [make_machine() for _ in range(5)]
        for machine in made:
            await storage.create_machine(machine)
        pages: list[list[UUID]] = []
        after: UUID | None = None
        while page := await storage.read_machines(2, after):
            pages.append([m.id for m in page])
            after = page[-1].id
        assert [len(page) for page in pages] == [2, 2, 1]
        assert [id_ for page in pages for id_ in page] == sorted(m.id for m in made)
        first = made[0]
        await storage.delete_machine(first.id)
        assert await storage.read_machine(first.id) is None
        assert first.id not in [m.id for m in await storage.read_machines(10)]

    async def test_a_machine_is_found_by_its_name(self, storage: CloudPoolStorageInterface) -> None:
        machine = make_machine()
        await storage.create_machine(machine)
        assert await storage.read_by_name(machine.name) == machine
        assert await storage.read_by_name("acme-vm-pnone") is None

    async def test_an_erasure_is_asked_once_per_session_until_it_is_done(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        tenant, session = new_id(), new_id()
        now = utcnow()
        first = PoolErasure(id=new_id(), created_at=now, tenant_id=tenant, session_id=session)
        assert await storage.ask_erase(first) == first
        assert await storage.ask_erase(first.model_copy(update={"id": new_id()})) == first
        other = PoolErasure(
            id=new_id(),
            created_at=now + timedelta(seconds=1),
            tenant_id=tenant,
            session_id=new_id(),
        )
        await storage.ask_erase(other)
        assert await storage.read_erasures(10) == [first, other]
        assert await storage.read_erasures(1) == [first]
        await storage.delete_erasure(first.id)
        assert await storage.read_erasures(10) == [other]
