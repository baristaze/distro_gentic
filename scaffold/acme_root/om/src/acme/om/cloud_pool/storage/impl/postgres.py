from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from acme.om.base import EMPTY_UUID
from acme.om.cloud_pool.rules import warm_to_start
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.storage.tables.pool_machines import PoolMachines
from acme.om.cloud_pool.types.machine import PoolMachine
from acme.om.exceptions import UniqueKeyTaken
from acme.om.storage.impl.pg_base import PgStorageBase, violated_constraint
from acme.om.storage.utils.translation import to_model, to_row

WARM_LOCK = int.from_bytes(b"warmpool", "big") >> 1
"""The advisory lock one process holds while it counts the warm machines and
writes the ones it will start, so two sweeps never start one twice."""


class CloudPoolStoragePostgresImpl(PgStorageBase, CloudPoolStorageInterface):
    """The pool's rows are the platform's own, read and written in the system
    scope: a warm machine names no tenant."""

    async def create_machine(self, machine: PoolMachine) -> None:
        async with self._session_for(PoolMachines, org_id=EMPTY_UUID) as session:
            session.add(to_row(machine, PoolMachines))
            await self._commit(session, machine)

    async def reserve_warm(self, wanted: int, made: Sequence[PoolMachine]) -> list[PoolMachine]:
        count = (
            select(func.count()).select_from(PoolMachines).where(PoolMachines.session_id.is_(None))
        )
        async with self._session_for(PoolMachines, org_id=EMPTY_UUID) as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": WARM_LOCK})
            warm = (await session.execute(count)).scalar_one()
            written = list(made[: warm_to_start(wanted, warm)])
            for machine in written:
                session.add(to_row(machine, PoolMachines))
            await self._commit(session, *written)
            return written

    async def read_machine(self, machine_id: UUID) -> PoolMachine | None:
        return await self._one(select(PoolMachines).where(PoolMachines.id == machine_id))

    async def read_by_key(self, key_digest: str) -> PoolMachine | None:
        return await self._one(select(PoolMachines).where(PoolMachines.key_digest == key_digest))

    async def read_of_session(self, org_id: UUID, session_id: UUID) -> PoolMachine | None:
        stmt = (
            select(PoolMachines)
            .where(PoolMachines.tenant_id == org_id, PoolMachines.session_id == session_id)
            .order_by(PoolMachines.created_at, PoolMachines.id)
            .limit(1)
        )
        return await self._one(stmt)

    async def read_of_tenant(self, org_id: UUID, limit: int) -> list[PoolMachine]:
        stmt = (
            select(PoolMachines)
            .where(PoolMachines.tenant_id == org_id)
            .order_by(PoolMachines.created_at, PoolMachines.id)
            .limit(limit)
        )
        return await self._all(stmt)

    async def read_machines(self, limit: int) -> list[PoolMachine]:
        stmt = select(PoolMachines).order_by(PoolMachines.created_at, PoolMachines.id).limit(limit)
        return await self._all(stmt)

    async def claim_warm(
        self,
        org_id: UUID,
        session_id: UUID,
        pool_id: UUID,
        bound_by: UUID,
        egress_open: bool,
    ) -> PoolMachine | None:
        stmt = (
            select(PoolMachines)
            .where(
                PoolMachines.session_id.is_(None),
                PoolMachines.started_at.is_not(None),
                PoolMachines.egress_open == egress_open,
            )
            .order_by(PoolMachines.created_at, PoolMachines.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            row.tenant_id = org_id
            row.session_id = session_id
            row.pool_id = pool_id
            row.bound_by = bound_by
            claimed = to_model(row, PoolMachine)
            await session.commit()
            return claimed

    async def mark_started(self, machine_id: UUID, at: datetime) -> None:
        await self._update(machine_id, started_at=at)

    async def spend_key(self, machine_id: UUID, key_digest: str) -> bool:
        stmt = (
            update(PoolMachines)
            .where(PoolMachines.id == machine_id, PoolMachines.key_digest == key_digest)
            .values(key_digest=None)
            .returning(PoolMachines.id)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            spent = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
            return spent is not None

    async def mark_enrolled(self, machine_id: UUID, host_id: UUID) -> None:
        await self._update(machine_id, host_id=host_id)

    async def mark_sealed(self, machine_id: UUID, at: datetime) -> None:
        await self._update(machine_id, sealed_at=at)

    async def rekey(
        self, machine_id: UUID, key_digest: str, restored_from: UUID | None
    ) -> PoolMachine | None:
        stmt = (
            update(PoolMachines)
            .where(PoolMachines.id == machine_id)
            .values(
                key_digest=key_digest,
                restored_from=restored_from,
                host_id=None,
                started_at=None,
                sealed_at=None,
            )
            .returning(PoolMachines)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            changed = None if row is None else to_model(row, PoolMachine)
            await session.commit()
            return changed

    async def delete_machine(self, machine_id: UUID) -> None:
        stmt = delete(PoolMachines).where(PoolMachines.id == machine_id)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def _update(self, machine_id: UUID, **values: Any) -> None:
        stmt = update(PoolMachines).where(PoolMachines.id == machine_id).values(**values)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def _one(self, stmt: Any) -> PoolMachine | None:
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, PoolMachine)

    async def _all(self, stmt: Any) -> list[PoolMachine]:
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            return [to_model(row, PoolMachine) for row in (await session.execute(stmt)).scalars()]

    @staticmethod
    async def _commit(session: Any, *machines: PoolMachine) -> None:
        try:
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            ids = ", ".join(str(machine.id) for machine in machines)
            raise UniqueKeyTaken(
                f"pool_machines {ids}: {violated_constraint(error) or 'a unique key'} is taken"
            ) from error
