import asyncio
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.om.cloud_pool.rules import warm_to_start
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.types.machine import PoolMachine
from acme.om.exceptions import UniqueKeyTaken


class CloudPoolStorageMemoryImpl(CloudPoolStorageInterface):
    """The pool's rows in one process, each change under one lock, as the
    Postgres impl holds them under its row locks."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._machines: dict[UUID, PoolMachine] = {}

    async def create_machine(self, machine: PoolMachine) -> None:
        async with self._lock:
            self._add(machine)

    async def reserve_warm(self, wanted: int, made: Sequence[PoolMachine]) -> list[PoolMachine]:
        async with self._lock:
            warm = sum(1 for machine in self._machines.values() if machine.warm)
            written = list(made[: warm_to_start(wanted, warm)])
            for machine in written:
                self._add(machine)
            return written

    async def read_machine(self, machine_id: UUID) -> PoolMachine | None:
        return self._machines.get(machine_id)

    async def read_by_key(self, key_digest: str) -> PoolMachine | None:
        return next(
            (m for m in self._machines.values() if m.key_digest == key_digest),
            None,
        )

    async def read_of_session(self, org_id: UUID, session_id: UUID) -> PoolMachine | None:
        return next(
            (
                m
                for m in self._oldest_first()
                if m.tenant_id == org_id and m.session_id == session_id
            ),
            None,
        )

    async def read_of_tenant(self, org_id: UUID, limit: int) -> list[PoolMachine]:
        return [m for m in self._oldest_first() if m.tenant_id == org_id][:limit]

    async def read_machines(self, limit: int) -> list[PoolMachine]:
        return self._oldest_first()[:limit]

    async def claim_warm(
        self,
        org_id: UUID,
        session_id: UUID,
        pool_id: UUID,
        bound_by: UUID,
        egress_open: bool,
    ) -> PoolMachine | None:
        async with self._lock:
            for machine in self._oldest_first():
                if (
                    machine.warm
                    and machine.started_at is not None
                    and machine.egress_open == egress_open
                ):
                    claimed = machine.model_copy(
                        update={
                            "tenant_id": org_id,
                            "session_id": session_id,
                            "pool_id": pool_id,
                            "bound_by": bound_by,
                        }
                    )
                    self._machines[machine.id] = claimed
                    return claimed
            return None

    async def mark_started(self, machine_id: UUID, at: datetime) -> None:
        await self._update(machine_id, started_at=at)

    async def spend_key(self, machine_id: UUID, key_digest: str) -> bool:
        async with self._lock:
            machine = self._machines.get(machine_id)
            if machine is None or machine.key_digest != key_digest:
                return False
            self._machines[machine_id] = machine.model_copy(update={"key_digest": None})
            return True

    async def mark_enrolled(self, machine_id: UUID, host_id: UUID) -> None:
        await self._update(machine_id, host_id=host_id)

    async def mark_sealed(self, machine_id: UUID, at: datetime) -> None:
        await self._update(machine_id, sealed_at=at)

    async def rekey(
        self, machine_id: UUID, key_digest: str, restored_from: UUID | None
    ) -> PoolMachine | None:
        return await self._update(
            machine_id,
            key_digest=key_digest,
            restored_from=restored_from,
            host_id=None,
            started_at=None,
            sealed_at=None,
        )

    async def delete_machine(self, machine_id: UUID) -> None:
        async with self._lock:
            self._machines.pop(machine_id, None)

    def _add(self, machine: PoolMachine) -> None:
        for held in self._machines.values():
            if held.name == machine.name or (
                machine.key_digest is not None and held.key_digest == machine.key_digest
            ):
                raise UniqueKeyTaken(f"pool_machines {machine.id}: a unique key is taken")
        self._machines[machine.id] = machine

    async def _update(self, machine_id: UUID, **update: object) -> PoolMachine | None:
        async with self._lock:
            machine = self._machines.get(machine_id)
            if machine is None:
                return None
            changed = machine.model_copy(update=update)
            self._machines[machine_id] = changed
            return changed

    def _oldest_first(self) -> list[PoolMachine]:
        return sorted(self._machines.values(), key=lambda m: (m.created_at, m.id))
