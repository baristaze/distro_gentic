"""The contract every cloud pool storage meets: a machine is found by its
key until the key is spent, by the session it serves, and by its tenant; a
warm machine is claimed once, and only once it started, at the egress
asked; and the warm machines a sweep writes never pass the count."""

from datetime import timedelta
from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.types.machine import PoolMachine
from acme.om.exceptions import UniqueKeyTaken


def make_machine(
    *,
    egress_open: bool = True,
    tenant_id: UUID | None = None,
    session_id: UUID | None = None,
    started: bool = True,
) -> PoolMachine:
    now = utcnow()
    return PoolMachine(
        id=new_id(),
        created_at=now,
        name=f"acme-vm-p{new_id().hex[:16]}",
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
        assert await storage.claim_warm(tenant, session, pool, person, True) is None
        claimed = await storage.claim_warm(tenant, session, pool, person, False)
        assert claimed is not None and claimed.id == closed.id
        assert (claimed.tenant_id, claimed.session_id, claimed.pool_id, claimed.bound_by) == (
            tenant,
            session,
            pool,
            person,
        )
        assert await storage.claim_warm(tenant, new_id(), pool, person, False) is None
        assert await storage.read_of_session(tenant, session) == claimed
        assert await storage.read_of_session(new_id(), session) is None
        assert await storage.read_of_tenant(tenant, 10) == [claimed]

    async def test_the_warm_machines_written_never_pass_the_count(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        await storage.create_machine(make_machine())
        await storage.create_machine(make_machine(tenant_id=new_id(), session_id=new_id()))
        made = [make_machine(started=False) for _ in range(3)]
        written = await storage.reserve_warm(2, made)
        assert written == made[:1], "one stands warm already"
        assert await storage.reserve_warm(2, [make_machine(started=False)]) == []
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
        again = await storage.rekey(machine.id, "a new digest", snapshot)
        assert again is not None
        assert (again.key_digest, again.restored_from, again.host_id) == (
            "a new digest",
            snapshot,
            None,
        )
        assert again.started_at is None and again.sealed_at is None
        later = at + timedelta(seconds=1)
        await storage.mark_started(machine.id, later)
        started = await storage.read_machine(machine.id)
        assert started is not None and started.started_at is not None
        assert await storage.rekey(new_id(), "none", None) is None

    async def test_a_deleted_machine_is_gone_and_the_oldest_comes_first(
        self, storage: CloudPoolStorageInterface
    ) -> None:
        first, second = make_machine(), make_machine()
        await storage.create_machine(first)
        await storage.create_machine(second)
        assert [m.id for m in await storage.read_machines(10)] == [first.id, second.id]
        await storage.delete_machine(first.id)
        assert await storage.read_machine(first.id) is None
        assert [m.id for m in await storage.read_machines(10)] == [second.id]
