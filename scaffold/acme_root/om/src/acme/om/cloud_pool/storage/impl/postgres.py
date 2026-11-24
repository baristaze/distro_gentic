from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from acme.om.base import EMPTY_UUID
from acme.om.cloud_pool.rules import warm_to_start
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.storage.tables.pool_archives import PoolArchives
from acme.om.cloud_pool.storage.tables.pool_limits import PoolLimits as PoolLimitsRows
from acme.om.cloud_pool.storage.tables.pool_tenant_limits import PoolTenantLimits
from acme.om.cloud_pool.storage.tables.pool_vms import PoolVms
from acme.om.cloud_pool.types.archive import PoolArchive
from acme.om.cloud_pool.types.limits import Full, PoolLimits, TenantPoolLimit
from acme.om.cloud_pool.types.vm import PoolClaim, PoolVm
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.storage.impl.pg_base import PgStorageBase, violated_constraint
from acme.om.storage.utils.translation import to_model, to_row, to_values

POOL_LOCK = int.from_bytes(b"warmpool", "big") >> 1
"""The advisory lock one process holds while it counts the pool's VMs and
writes or binds the ones it counted for: a claim, a refill, and the
sweep's taking of a warm VM, so no two pass a maximum together, two
sweeps never start one VM twice, and no claim binds a VM being
destroyed."""

_LOCKED = text("SELECT pg_advisory_xact_lock(:key)")


class CloudPoolStoragePostgresImpl(PgStorageBase, CloudPoolStorageInterface):
    """The pool's rows are the platform's own, read and written in the system
    scope, which each method names: a warm VM names no tenant."""

    async def create_vm(self, vm: PoolVm) -> None:
        async with self._session_for(PoolVms, org_id=EMPTY_UUID) as session:
            session.add(to_row(vm, PoolVms))
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise _taken(error, vm.id) from error

    async def claim(
        self, vm: PoolVm, *, most: int, tenant_most: int, warm: bool
    ) -> PoolClaim | Full:
        everyone = select(func.count()).select_from(PoolVms)
        tenants = everyone.where(PoolVms.tenant_id == vm.tenant_id)
        idle = (
            select(PoolVms)
            .where(PoolVms.agent_session_id.is_(None), PoolVms.started_at.is_not(None))
            .order_by(PoolVms.created_at, PoolVms.id)
            .limit(1)
            .with_for_update()
        )
        egress = idle.where(PoolVms.egress_open == vm.egress_open)
        # A warm VM that runs, else one asleep; never one started to sleep
        # that sleeps not yet.
        running = egress.where(PoolVms.hibernates.is_(False))
        asleep = egress.where(PoolVms.hibernated_at.is_not(None))
        async with self._session_for(PoolVms, org_id=EMPTY_UUID) as session:
            await session.execute(_LOCKED, {"key": POOL_LOCK})
            if (await session.execute(tenants)).scalar_one() >= tenant_most:
                await session.rollback()
                return Full.TENANT
            row = (await session.execute(running)).scalar_one_or_none() if warm else None
            if row is None and warm:
                row = (await session.execute(asleep)).scalar_one_or_none()
                if row is not None:
                    # It slept holding no key: it wakes with the claim's.
                    row.key_digest = vm.key_digest
            if row is not None:
                row.tenant_id = vm.tenant_id
                row.agent_session_id = vm.agent_session_id
                row.pool_id = vm.pool_id
                row.bound_by = vm.bound_by
                row.restored_from = vm.restored_from
                row.bound_at = vm.bound_at
                claimed = to_model(row, PoolVm)
                await session.commit()
                return PoolClaim(vm=claimed)
            displaced: PoolVm | None = None
            if (await session.execute(everyone)).scalar_one() >= most:
                # Its own row takes the place of an idle warm VM, whose row
                # goes under this lock, so no claim binds it.
                place = (await session.execute(idle)).scalar_one_or_none()
                if place is None:
                    await session.rollback()
                    return Full.POOL
                displaced = to_model(place, PoolVm)
                await session.execute(delete(PoolVms).where(PoolVms.id == place.id))
            session.add(to_row(vm, PoolVms))
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise _taken(error, vm.id) from error
            return PoolClaim(vm=vm, displaced=displaced)

    async def reserve_warm(
        self, wanted: int, most: int, made: Sequence[PoolVm], *, hibernates: bool = False
    ) -> int:
        everyone = select(func.count()).select_from(PoolVms)
        warm = everyone.where(
            PoolVms.agent_session_id.is_(None), PoolVms.hibernates.is_(hibernates)
        )
        async with self._session_for(PoolVms, org_id=EMPTY_UUID) as session:
            await session.execute(_LOCKED, {"key": POOL_LOCK})
            standing = (await session.execute(warm)).scalar_one()
            held = (await session.execute(everyone)).scalar_one()
            written = list(made[: warm_to_start(wanted, standing, most - held)])
            for vm in written:
                session.add(to_row(vm, PoolVms))
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise _taken(error, *(vm.id for vm in written)) from error
            return len(written)

    async def take_warm(self, vm_id: UUID) -> bool:
        stmt = (
            delete(PoolVms)
            .where(PoolVms.id == vm_id, PoolVms.agent_session_id.is_(None))
            .returning(PoolVms.id)
        )
        async with self._session_for(PoolVms, org_id=EMPTY_UUID) as session:
            await session.execute(_LOCKED, {"key": POOL_LOCK})
            taken = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
            return taken is not None

    async def take_to_sleep(self, vm_id: UUID, key_digest: str) -> bool:
        stmt = (
            update(PoolVms)
            .where(
                PoolVms.id == vm_id,
                PoolVms.agent_session_id.is_(None),
                PoolVms.hibernates.is_(True),
                PoolVms.hibernated_at.is_(None),
                PoolVms.key_digest == key_digest,
            )
            .values(key_digest=None)
            .returning(PoolVms.id)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            taken = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
            return taken is not None

    async def mark_hibernated(self, vm_id: UUID, at: datetime) -> None:
        stmt = (
            update(PoolVms)
            .where(PoolVms.id == vm_id, PoolVms.agent_session_id.is_(None))
            .values(hibernated_at=at)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def read_vm(self, vm_id: UUID) -> PoolVm | None:
        stmt = select(PoolVms).where(PoolVms.id == vm_id)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, PoolVm)

    async def read_by_key(self, key_digest: str) -> PoolVm | None:
        stmt = select(PoolVms).where(PoolVms.key_digest == key_digest)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, PoolVm)

    async def read_by_name(self, name: str) -> PoolVm | None:
        stmt = select(PoolVms).where(PoolVms.name == name)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, PoolVm)

    async def read_of_session(self, tenant_id: UUID, agent_session_id: UUID) -> PoolVm | None:
        stmt = (
            select(PoolVms)
            .where(PoolVms.tenant_id == tenant_id, PoolVms.agent_session_id == agent_session_id)
            .order_by(PoolVms.created_at, PoolVms.id)
            .limit(1)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, PoolVm)

    async def read_of_tenant(self, tenant_id: UUID, limit: int) -> list[PoolVm]:
        stmt = (
            select(PoolVms)
            .where(PoolVms.tenant_id == tenant_id)
            .order_by(PoolVms.created_at, PoolVms.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            return [to_model(row, PoolVm) for row in (await session.execute(stmt)).scalars()]

    async def read_vms(self, limit: int, after: UUID | None = None) -> list[PoolVm]:
        stmt = select(PoolVms).order_by(PoolVms.id).limit(limit)
        if after is not None:
            stmt = stmt.where(PoolVms.id > after)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            return [to_model(row, PoolVm) for row in (await session.execute(stmt)).scalars()]

    async def mark_started(self, vm_id: UUID, at: datetime) -> None:
        stmt = update(PoolVms).where(PoolVms.id == vm_id).values(started_at=at)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def spend_key(self, vm_id: UUID, key_digest: str) -> bool:
        stmt = (
            update(PoolVms)
            .where(PoolVms.id == vm_id, PoolVms.key_digest == key_digest)
            .values(key_digest=None)
            .returning(PoolVms.id)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            spent = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
            return spent is not None

    async def mark_enrolled(self, vm_id: UUID, host_id: UUID) -> None:
        stmt = update(PoolVms).where(PoolVms.id == vm_id).values(host_id=host_id)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def mark_sealed(self, vm_id: UUID, at: datetime) -> None:
        stmt = update(PoolVms).where(PoolVms.id == vm_id).values(sealed_at=at)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def rekey(self, vm_id: UUID, key_digest: str, at: datetime) -> PoolVm | None:
        stmt = (
            update(PoolVms)
            .where(PoolVms.id == vm_id)
            .values(
                key_digest=key_digest,
                host_id=None,
                bound_at=at,
                sealed_at=None,
            )
            .returning(PoolVms)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            changed = None if row is None else to_model(row, PoolVm)
            await session.commit()
            return changed

    async def delete_vm(self, vm_id: UUID) -> None:
        stmt = delete(PoolVms).where(PoolVms.id == vm_id)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def keep_archive(self, archive: PoolArchive) -> None:
        stmt = (
            insert(PoolArchives)
            .values(
                id=archive.id,
                created_at=archive.created_at,
                tenant_id=archive.tenant_id,
                agent_session_id=archive.agent_session_id,
                kept_at=archive.kept_at,
            )
            .on_conflict_do_update(
                index_elements=[PoolArchives.tenant_id, PoolArchives.agent_session_id],
                set_={"kept_at": archive.kept_at},
            )
        )
        async with self._session_for(PoolArchives, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def read_archives(self, before: datetime, limit: int) -> list[PoolArchive]:
        stmt = (
            select(PoolArchives)
            .where(PoolArchives.kept_at < before)
            .order_by(PoolArchives.kept_at, PoolArchives.agent_session_id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            return [to_model(row, PoolArchive) for row in (await session.execute(stmt)).scalars()]

    async def delete_archive(self, tenant_id: UUID, agent_session_id: UUID) -> None:
        stmt = delete(PoolArchives).where(
            PoolArchives.tenant_id == tenant_id, PoolArchives.agent_session_id == agent_session_id
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def delete_tenant_archives(self, tenant_id: UUID) -> int:
        stmt = delete(PoolArchives).where(PoolArchives.tenant_id == tenant_id)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            gone = cast(CursorResult[Any], await session.execute(stmt)).rowcount
            await session.commit()
            return gone

    async def read_limits(self) -> PoolLimits | None:
        stmt = select(PoolLimitsRows).order_by(PoolLimitsRows.version.desc()).limit(1)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, PoolLimits)

    async def write_limits(self, limits: PoolLimits, version: int | None) -> PoolLimits:
        # Every version is a row of its own: the highest holds, and the
        # version's unique index lets one of two writes from one version land.
        head = select(func.max(PoolLimitsRows.version))
        async with self._session_for(PoolLimitsRows, org_id=EMPTY_UUID) as session:
            if (await session.execute(head)).scalar_one_or_none() != version:
                await session.rollback()
                raise PreconditionFailed("the cloud pool's limits were written meanwhile")
            session.add(to_row(limits, PoolLimitsRows))
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise PreconditionFailed(
                    "the cloud pool's limits were written meanwhile"
                ) from error
            return limits

    async def read_tenant_limit(self, org_id: UUID) -> TenantPoolLimit | None:
        stmt = select(PoolTenantLimits).where(PoolTenantLimits.org_id == org_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, TenantPoolLimit)

    async def write_tenant_limit(
        self, org_id: UUID, limit: TenantPoolLimit, version: int | None
    ) -> TenantPoolLimit:
        meanwhile = f"org {org_id}'s VM maximum was written meanwhile"
        async with self._session_for(PoolTenantLimits, org_id=org_id) as session:
            if version is None:
                session.add(to_row(limit, PoolTenantLimits, org_id=org_id))
                try:
                    await session.commit()
                except IntegrityError as error:
                    await session.rollback()
                    raise PreconditionFailed(meanwhile) from error
                return limit
            # The version is in the WHERE, so two writers from one read
            # cannot both land.
            values = {k: v for k, v in to_values(limit, PoolTenantLimits).items() if k != "id"}
            stmt = (
                update(PoolTenantLimits)
                .where(PoolTenantLimits.org_id == org_id, PoolTenantLimits.version == version)
                .values(**values)
                .returning(PoolTenantLimits)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                await session.rollback()
                raise PreconditionFailed(meanwhile)
            written = to_model(row, TenantPoolLimit)
            await session.commit()
            return written

    async def delete_tenant_limit(self, org_id: UUID) -> TenantPoolLimit | None:
        stmt = (
            delete(PoolTenantLimits)
            .where(PoolTenantLimits.org_id == org_id)
            .returning(PoolTenantLimits)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            deleted = None if row is None else to_model(row, TenantPoolLimit)
            await session.commit()
            return deleted


def _taken(error: IntegrityError, *ids: UUID) -> UniqueKeyTaken:
    named = ", ".join(str(id_) for id_ in ids)
    return UniqueKeyTaken(
        f"pool_vms {named}: {violated_constraint(error) or 'a unique key'} is taken"
    )
