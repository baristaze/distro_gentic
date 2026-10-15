import asyncio
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.om.cloud_pool.rules import warm_to_start
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.types.erasure import PoolErasure
from acme.om.cloud_pool.types.machine import PoolVm
from acme.om.exceptions import UniqueKeyTaken


class CloudPoolStorageMemoryImpl(CloudPoolStorageInterface):
    """The pool's rows in one process, each change under one lock, as the
    Postgres impl holds them under its row locks."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._vms: dict[UUID, PoolVm] = {}
        self._erasures: dict[tuple[UUID, UUID], PoolErasure] = {}

    async def create_machine(self, machine: PoolVm) -> None:
        async with self._lock:
            self._add(machine)

    async def reserve_warm(self, wanted: int, made: Sequence[PoolVm]) -> int:
        async with self._lock:
            warm = sum(1 for machine in self._vms.values() if machine.warm)
            written = list(made[: warm_to_start(wanted, warm)])
            for machine in written:
                self._add(machine)
            return len(written)

    async def read_machine(self, machine_id: UUID) -> PoolVm | None:
        return self._vms.get(machine_id)

    async def read_by_key(self, key_digest: str) -> PoolVm | None:
        return next(
            (m for m in self._vms.values() if m.key_digest == key_digest),
            None,
        )

    async def read_by_name(self, name: str) -> PoolVm | None:
        return next((m for m in self._vms.values() if m.name == name), None)

    async def read_of_session(self, tenant_id: UUID, agent_session_id: UUID) -> PoolVm | None:
        return next(
            (
                m
                for m in self._oldest_first()
                if m.tenant_id == tenant_id and m.agent_session_id == agent_session_id
            ),
            None,
        )

    async def read_of_tenant(self, tenant_id: UUID, limit: int) -> list[PoolVm]:
        return [m for m in self._oldest_first() if m.tenant_id == tenant_id][:limit]

    async def read_machines(self, limit: int, after: UUID | None = None) -> list[PoolVm]:
        by_id = sorted(self._vms.values(), key=lambda m: m.id)
        return [m for m in by_id if after is None or m.id > after][:limit]

    async def claim_warm(
        self,
        tenant_id: UUID,
        agent_session_id: UUID,
        pool_id: UUID,
        bound_by: UUID,
        egress_open: bool,
        at: datetime,
    ) -> PoolVm | None:
        async with self._lock:
            for machine in self._oldest_first():
                if (
                    machine.warm
                    and machine.started_at is not None
                    and machine.egress_open == egress_open
                ):
                    claimed = machine.model_copy(
                        update={
                            "tenant_id": tenant_id,
                            "agent_session_id": agent_session_id,
                            "pool_id": pool_id,
                            "bound_by": bound_by,
                            "bound_at": at,
                        }
                    )
                    self._vms[machine.id] = claimed
                    return claimed
            return None

    async def mark_started(self, machine_id: UUID, at: datetime) -> None:
        await self._update(machine_id, started_at=at)

    async def spend_key(self, machine_id: UUID, key_digest: str) -> bool:
        async with self._lock:
            machine = self._vms.get(machine_id)
            if machine is None or machine.key_digest != key_digest:
                return False
            self._vms[machine_id] = machine.model_copy(update={"key_digest": None})
            return True

    async def mark_enrolled(self, machine_id: UUID, host_id: UUID) -> None:
        await self._update(machine_id, host_id=host_id)

    async def mark_sealed(self, machine_id: UUID, at: datetime) -> None:
        await self._update(machine_id, sealed_at=at)

    async def rekey(
        self, machine_id: UUID, key_digest: str, restored_from: UUID | None, at: datetime
    ) -> PoolVm | None:
        return await self._update(
            machine_id,
            key_digest=key_digest,
            restored_from=restored_from,
            host_id=None,
            bound_at=at,
            sealed_at=None,
        )

    async def delete_machine(self, machine_id: UUID) -> None:
        async with self._lock:
            self._vms.pop(machine_id, None)

    async def ask_erase(self, erasure: PoolErasure) -> PoolErasure:
        async with self._lock:
            return self._erasures.setdefault((erasure.tenant_id, erasure.agent_session_id), erasure)

    async def read_erasures(self, limit: int) -> list[PoolErasure]:
        asked = sorted(self._erasures.values(), key=lambda e: (e.created_at, e.id))
        return asked[:limit]

    async def delete_erasure(self, erasure_id: UUID) -> None:
        async with self._lock:
            for at, erasure in list(self._erasures.items()):
                if erasure.id == erasure_id:
                    del self._erasures[at]

    def _add(self, machine: PoolVm) -> None:
        for held in self._vms.values():
            if held.name == machine.name or (
                machine.key_digest is not None and held.key_digest == machine.key_digest
            ):
                raise UniqueKeyTaken(f"pool_vms {machine.id}: a unique key is taken")
        self._vms[machine.id] = machine

    async def _update(self, machine_id: UUID, **update: object) -> PoolVm | None:
        async with self._lock:
            machine = self._vms.get(machine_id)
            if machine is None:
                return None
            changed = machine.model_copy(update=update)
            self._vms[machine_id] = changed
            return changed

    def _oldest_first(self) -> list[PoolVm]:
        return sorted(self._vms.values(), key=lambda m: (m.created_at, m.id))
