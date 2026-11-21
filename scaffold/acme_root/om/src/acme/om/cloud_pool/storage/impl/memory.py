import asyncio
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.om.cloud_pool.rules import warm_to_start
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.types.archive import PoolArchive
from acme.om.cloud_pool.types.limits import Full, PoolLimits, TenantPoolLimit
from acme.om.cloud_pool.types.vm import PoolClaim, PoolVm
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken


class CloudPoolStorageMemoryImpl(CloudPoolStorageInterface):
    """The pool's rows in one process, each change under one lock, as the
    Postgres impl holds them under its row locks."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._vms: dict[UUID, PoolVm] = {}
        self._archives: dict[tuple[UUID, UUID], PoolArchive] = {}
        self._limits: PoolLimits | None = None
        self._tenant_limits: dict[UUID, TenantPoolLimit] = {}

    async def create_vm(self, vm: PoolVm) -> None:
        async with self._lock:
            self._add(vm)

    async def claim(
        self, vm: PoolVm, *, most: int, tenant_most: int, warm: bool
    ) -> PoolClaim | Full:
        async with self._lock:
            if sum(1 for held in self._vms.values() if held.tenant_id == vm.tenant_id) >= (
                tenant_most
            ):
                return Full.TENANT
            if warm:
                for held in self._oldest_first():
                    if (
                        held.warm
                        and held.started_at is not None
                        and (held.egress_open == vm.egress_open)
                    ):
                        claimed = held.model_copy(
                            update={
                                "tenant_id": vm.tenant_id,
                                "agent_session_id": vm.agent_session_id,
                                "pool_id": vm.pool_id,
                                "bound_by": vm.bound_by,
                                "restored_from": vm.restored_from,
                                "bound_at": vm.bound_at,
                            }
                        )
                        self._vms[held.id] = claimed
                        return PoolClaim(vm=claimed)
            if len(self._vms) < most:
                self._add(vm)
                return PoolClaim(vm=vm)
            # Its own row takes the place of an idle warm VM, whose row goes
            # under this lock, so no claim binds it.
            displaced = next(
                (
                    held
                    for held in self._oldest_first()
                    if held.warm and held.started_at is not None
                ),
                None,
            )
            if displaced is None:
                return Full.POOL
            self._add(vm)
            del self._vms[displaced.id]
            return PoolClaim(vm=vm, displaced=displaced)

    async def reserve_warm(self, wanted: int, most: int, made: Sequence[PoolVm]) -> int:
        async with self._lock:
            warm = sum(1 for vm in self._vms.values() if vm.warm)
            written = list(made[: warm_to_start(wanted, warm, most - len(self._vms))])
            for vm in written:
                self._add(vm)
            return len(written)

    async def take_warm(self, vm_id: UUID) -> bool:
        async with self._lock:
            vm = self._vms.get(vm_id)
            if vm is None or not vm.warm:
                return False
            del self._vms[vm_id]
            return True

    async def read_vm(self, vm_id: UUID) -> PoolVm | None:
        return self._vms.get(vm_id)

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

    async def read_vms(self, limit: int, after: UUID | None = None) -> list[PoolVm]:
        by_id = sorted(self._vms.values(), key=lambda m: m.id)
        return [m for m in by_id if after is None or m.id > after][:limit]

    async def mark_started(self, vm_id: UUID, at: datetime) -> None:
        await self._update(vm_id, started_at=at)

    async def spend_key(self, vm_id: UUID, key_digest: str) -> bool:
        async with self._lock:
            vm = self._vms.get(vm_id)
            if vm is None or vm.key_digest != key_digest:
                return False
            self._vms[vm_id] = vm.model_copy(update={"key_digest": None})
            return True

    async def mark_enrolled(self, vm_id: UUID, host_id: UUID) -> None:
        await self._update(vm_id, host_id=host_id)

    async def mark_sealed(self, vm_id: UUID, at: datetime) -> None:
        await self._update(vm_id, sealed_at=at)

    async def rekey(self, vm_id: UUID, key_digest: str, at: datetime) -> PoolVm | None:
        return await self._update(
            vm_id,
            key_digest=key_digest,
            host_id=None,
            bound_at=at,
            sealed_at=None,
        )

    async def delete_vm(self, vm_id: UUID) -> None:
        async with self._lock:
            self._vms.pop(vm_id, None)

    async def keep_archive(self, archive: PoolArchive) -> None:
        async with self._lock:
            at = (archive.tenant_id, archive.agent_session_id)
            held = self._archives.get(at)
            moved = None if held is None else held.model_copy(update={"kept_at": archive.kept_at})
            self._archives[at] = archive if moved is None else moved

    async def read_archives(self, before: datetime, limit: int) -> list[PoolArchive]:
        kept = [archive for archive in self._archives.values() if archive.kept_at < before]
        kept.sort(key=lambda archive: (archive.kept_at, archive.agent_session_id))
        return kept[:limit]

    async def delete_archive(self, tenant_id: UUID, agent_session_id: UUID) -> None:
        async with self._lock:
            self._archives.pop((tenant_id, agent_session_id), None)

    async def delete_tenant_archives(self, tenant_id: UUID) -> int:
        async with self._lock:
            held = [at for at in self._archives if at[0] == tenant_id]
            for at in held:
                del self._archives[at]
            return len(held)

    async def read_limits(self) -> PoolLimits | None:
        return self._limits

    async def write_limits(self, limits: PoolLimits, version: int | None) -> PoolLimits:
        async with self._lock:
            standing = None if self._limits is None else self._limits.version
            if standing != version:
                raise PreconditionFailed("the cloud pool's limits were written meanwhile")
            self._limits = limits
            return limits

    async def read_tenant_limit(self, org_id: UUID) -> TenantPoolLimit | None:
        return self._tenant_limits.get(org_id)

    async def write_tenant_limit(
        self, org_id: UUID, limit: TenantPoolLimit, version: int | None
    ) -> TenantPoolLimit:
        async with self._lock:
            held = self._tenant_limits.get(org_id)
            if (None if held is None else held.version) != version:
                raise PreconditionFailed(f"org {org_id}'s VM maximum was written meanwhile")
            self._tenant_limits[org_id] = limit
            return limit

    async def delete_tenant_limit(self, org_id: UUID) -> TenantPoolLimit | None:
        async with self._lock:
            return self._tenant_limits.pop(org_id, None)

    def _add(self, vm: PoolVm) -> None:
        for held in self._vms.values():
            if held.name == vm.name or (
                vm.key_digest is not None and held.key_digest == vm.key_digest
            ):
                raise UniqueKeyTaken(f"pool_vms {vm.id}: a unique key is taken")
        self._vms[vm.id] = vm

    async def _update(self, vm_id: UUID, **update: object) -> PoolVm | None:
        async with self._lock:
            vm = self._vms.get(vm_id)
            if vm is None:
                return None
            changed = vm.model_copy(update=update)
            self._vms[vm_id] = changed
            return changed

    def _oldest_first(self) -> list[PoolVm]:
        return sorted(self._vms.values(), key=lambda m: (m.created_at, m.id))
