from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from acme.om.base import EMPTY_UUID
from acme.om.cloud_pool.rules import warm_to_start
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.storage.tables.pool_erasures import PoolErasures
from acme.om.cloud_pool.storage.tables.pool_vms import PoolVms
from acme.om.cloud_pool.types.erasure import PoolErasure
from acme.om.cloud_pool.types.machine import PoolVm
from acme.om.exceptions import UniqueKeyTaken
from acme.om.storage.impl.pg_base import PgStorageBase, violated_constraint
from acme.om.storage.utils.translation import to_model, to_row

WARM_LOCK = int.from_bytes(b"warmpool", "big") >> 1
"""The advisory lock one process holds while it counts the warm machines and
writes the ones it will start, so two sweeps never start one twice."""


class CloudPoolStoragePostgresImpl(PgStorageBase, CloudPoolStorageInterface):
    """The pool's rows are the platform's own, read and written in the system
    scope, which each method names: a warm machine names no tenant."""

    async def create_machine(self, machine: PoolVm) -> None:
        async with self._session_for(PoolVms, org_id=EMPTY_UUID) as session:
            session.add(to_row(machine, PoolVms))
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise _taken(error, machine.id) from error

    async def reserve_warm(self, wanted: int, made: Sequence[PoolVm]) -> int:
        count = select(func.count()).select_from(PoolVms).where(PoolVms.session_id.is_(None))
        async with self._session_for(PoolVms, org_id=EMPTY_UUID) as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": WARM_LOCK})
            warm = (await session.execute(count)).scalar_one()
            written = list(made[: warm_to_start(wanted, warm)])
            for machine in written:
                session.add(to_row(machine, PoolVms))
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise _taken(error, *(machine.id for machine in written)) from error
            return len(written)

    async def read_machine(self, machine_id: UUID) -> PoolVm | None:
        stmt = select(PoolVms).where(PoolVms.id == machine_id)
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

    async def read_of_session(self, tenant_id: UUID, session_id: UUID) -> PoolVm | None:
        stmt = (
            select(PoolVms)
            .where(PoolVms.tenant_id == tenant_id, PoolVms.session_id == session_id)
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

    async def read_machines(self, limit: int, after: UUID | None = None) -> list[PoolVm]:
        stmt = select(PoolVms).order_by(PoolVms.id).limit(limit)
        if after is not None:
            stmt = stmt.where(PoolVms.id > after)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            return [to_model(row, PoolVm) for row in (await session.execute(stmt)).scalars()]

    async def claim_warm(
        self,
        tenant_id: UUID,
        session_id: UUID,
        pool_id: UUID,
        bound_by: UUID,
        egress_open: bool,
        at: datetime,
    ) -> PoolVm | None:
        stmt = (
            select(PoolVms)
            .where(
                PoolVms.session_id.is_(None),
                PoolVms.started_at.is_not(None),
                PoolVms.egress_open == egress_open,
            )
            .order_by(PoolVms.created_at, PoolVms.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            row.tenant_id = tenant_id
            row.session_id = session_id
            row.pool_id = pool_id
            row.bound_by = bound_by
            row.bound_at = at
            claimed = to_model(row, PoolVm)
            await session.commit()
            return claimed

    async def mark_started(self, machine_id: UUID, at: datetime) -> None:
        stmt = update(PoolVms).where(PoolVms.id == machine_id).values(started_at=at)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def spend_key(self, machine_id: UUID, key_digest: str) -> bool:
        stmt = (
            update(PoolVms)
            .where(PoolVms.id == machine_id, PoolVms.key_digest == key_digest)
            .values(key_digest=None)
            .returning(PoolVms.id)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            spent = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
            return spent is not None

    async def mark_enrolled(self, machine_id: UUID, host_id: UUID) -> None:
        stmt = update(PoolVms).where(PoolVms.id == machine_id).values(host_id=host_id)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def mark_sealed(self, machine_id: UUID, at: datetime) -> None:
        stmt = update(PoolVms).where(PoolVms.id == machine_id).values(sealed_at=at)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def rekey(
        self, machine_id: UUID, key_digest: str, restored_from: UUID | None, at: datetime
    ) -> PoolVm | None:
        stmt = (
            update(PoolVms)
            .where(PoolVms.id == machine_id)
            .values(
                key_digest=key_digest,
                restored_from=restored_from,
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

    async def delete_machine(self, machine_id: UUID) -> None:
        stmt = delete(PoolVms).where(PoolVms.id == machine_id)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def ask_erase(self, erasure: PoolErasure) -> PoolErasure:
        asked = (
            insert(PoolErasures)
            .values(
                id=erasure.id,
                created_at=erasure.created_at,
                tenant_id=erasure.tenant_id,
                session_id=erasure.session_id,
            )
            .on_conflict_do_nothing(
                index_elements=[PoolErasures.tenant_id, PoolErasures.session_id]
            )
        )
        standing = select(PoolErasures).where(
            PoolErasures.tenant_id == erasure.tenant_id,
            PoolErasures.session_id == erasure.session_id,
        )
        async with self._session_for(PoolErasures, org_id=EMPTY_UUID) as session:
            await session.execute(asked)
            stood = to_model((await session.execute(standing)).scalar_one(), PoolErasure)
            await session.commit()
            return stood

    async def read_erasures(self, limit: int) -> list[PoolErasure]:
        stmt = select(PoolErasures).order_by(PoolErasures.created_at, PoolErasures.id).limit(limit)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            return [to_model(row, PoolErasure) for row in (await session.execute(stmt)).scalars()]

    async def delete_erasure(self, erasure_id: UUID) -> None:
        stmt = delete(PoolErasures).where(PoolErasures.id == erasure_id)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()


def _taken(error: IntegrityError, *ids: UUID) -> UniqueKeyTaken:
    named = ", ".join(str(id_) for id_ in ids)
    return UniqueKeyTaken(
        f"pool_vms {named}: {violated_constraint(error) or 'a unique key'} is taken"
    )
