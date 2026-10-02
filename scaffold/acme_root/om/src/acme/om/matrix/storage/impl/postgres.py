from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from acme.om.base import EMPTY_UUID
from acme.om.exceptions import PreconditionFailed
from acme.om.matrix.storage import MatrixStorageInterface, MatrixTenantStorageInterface
from acme.om.matrix.storage.tables.benchmark_results import BenchmarkResults
from acme.om.matrix.storage.tables.fill_overrides import FillOverrides
from acme.om.matrix.storage.tables.matrix_pins import MatrixPins
from acme.om.matrix.storage.tables.matrix_versions import MatrixVersions
from acme.om.matrix.storage.tables.model_retirements import ModelRetirements
from acme.om.matrix.types.matrix import MatrixStatus, MatrixVersion
from acme.om.matrix.types.record import BenchmarkResult, ModelRef, Retirement
from acme.om.matrix.types.tenant import FillOverride, MatrixPin
from acme.om.models.types.fill import ModelRole
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values


class MatrixStoragePostgresImpl(PgStorageBase, MatrixStorageInterface):
    """The global rows, each statement in the system scope (`EMPTY_UUID`):
    the tables carry no policy, and no tenant names them."""

    async def create_version(self, version: MatrixVersion) -> None:
        async with self._session_for(MatrixVersions, org_id=EMPTY_UUID) as session:
            session.add(to_row(version, MatrixVersions))
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise PreconditionFailed(
                    f"matrix version {version.number} is written already"
                ) from error

    async def read_version(self, number: int) -> MatrixVersion | None:
        stmt = select(MatrixVersions).where(MatrixVersions.number == number)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, MatrixVersion)

    async def read_latest(self, status: MatrixStatus | None) -> MatrixVersion | None:
        stmt = select(MatrixVersions).order_by(MatrixVersions.number.desc()).limit(1)
        if status is not None:
            stmt = stmt.where(MatrixVersions.status == status.value)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, MatrixVersion)

    async def publish_version(
        self, number: int, published_at: datetime, published_by: UUID
    ) -> MatrixVersion | None:
        later = aliased(MatrixVersions)
        stmt = (
            update(MatrixVersions)
            .where(
                MatrixVersions.number == number,
                MatrixVersions.status == MatrixStatus.PENDING.value,
                ~exists().where(
                    later.status == MatrixStatus.PUBLISHED.value, later.number > number
                ),
            )
            .values(
                status=MatrixStatus.PUBLISHED.value,
                published_at=published_at,
                published_by=published_by,
            )
            .returning(MatrixVersions)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            published = None if row is None else to_model(row, MatrixVersion)
            await session.commit()
            return published

    async def add_result(self, result: BenchmarkResult) -> None:
        stmt = (
            insert(BenchmarkResults)
            .values(**to_values(result, BenchmarkResults))
            .on_conflict_do_nothing(index_elements=[BenchmarkResults.id])
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            await session.commit()

    async def read_results(self, model: ModelRef, limit: int) -> list[BenchmarkResult]:
        stmt = (
            select(BenchmarkResults)
            .where(
                BenchmarkResults.provider == model.provider.value,
                BenchmarkResults.model == model.model,
            )
            .order_by(BenchmarkResults.created_at.desc(), BenchmarkResults.id.desc())
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            rows = (await session.execute(stmt)).scalars()
            return [to_model(row, BenchmarkResult) for row in rows]

    async def add_retirement(self, retirement: Retirement) -> Retirement:
        stmt = (
            insert(ModelRetirements)
            .values(**to_values(retirement, ModelRetirements))
            .on_conflict_do_nothing(
                index_elements=[ModelRetirements.provider, ModelRetirements.model]
            )
        )
        held = select(ModelRetirements).where(
            ModelRetirements.provider == retirement.provider.value,
            ModelRetirements.model == retirement.model,
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(stmt)
            row = (await session.execute(held)).scalar_one()
            stored = to_model(row, Retirement)
            await session.commit()
            return stored

    async def read_retirements(self, limit: int) -> list[Retirement]:
        stmt = (
            select(ModelRetirements)
            .order_by(ModelRetirements.created_at.desc(), ModelRetirements.id.desc())
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            rows = (await session.execute(stmt)).scalars()
            return [to_model(row, Retirement) for row in rows]


class MatrixTenantStoragePostgresImpl(PgStorageBase, MatrixTenantStorageInterface):
    async def write_pin(self, org_id: UUID, pin: MatrixPin) -> MatrixPin:
        stmt = (
            insert(MatrixPins)
            .values(**to_values(pin, MatrixPins), org_id=org_id)
            .on_conflict_do_nothing()
        )
        held = select(MatrixPins).where(
            MatrixPins.org_id == org_id,
            MatrixPins.session_id == pin.session_id,
            MatrixPins.fill_set_version == pin.fill_set_version,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            row = (await session.execute(held)).scalar_one_or_none()
            await session.commit()
        if row is None:
            # The id is taken by a row this tenant cannot see.
            raise PreconditionFailed(f"matrix pin {pin.id} is another tenant's")
        return to_model(row, MatrixPin)

    async def read_pin(self, org_id: UUID, session_id: UUID) -> MatrixPin | None:
        stmt = (
            select(MatrixPins)
            .where(MatrixPins.org_id == org_id, MatrixPins.session_id == session_id)
            .order_by(MatrixPins.fill_set_version.desc())
            .limit(1)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, MatrixPin)

    async def write_override(self, org_id: UUID, override: FillOverride) -> FillOverride:
        values = to_values(override, FillOverrides)
        stmt = (
            insert(FillOverrides)
            .values(**values, org_id=org_id)
            .on_conflict_do_update(
                index_elements=[FillOverrides.org_id, FillOverrides.role],
                set_={
                    "fill": values["fill"],
                    "updated_at": values["updated_at"],
                    "updated_by": values["updated_by"],
                },
            )
            .returning(FillOverrides)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one()
            stored = to_model(row, FillOverride)
            await session.commit()
            return stored

    async def delete_override(self, org_id: UUID, role: ModelRole) -> bool:
        stmt = delete_batch(
            FillOverrides, FillOverrides.org_id == org_id, FillOverrides.role == role, limit=1
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            gone = deleted(await session.execute(stmt))
            await session.commit()
            return gone > 0

    async def read_overrides(self, org_id: UUID, limit: int) -> list[FillOverride]:
        stmt = (
            select(FillOverrides)
            .where(FillOverrides.org_id == org_id)
            .order_by(FillOverrides.role)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars()
            return [to_model(row, FillOverride) for row in rows]

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        pins = delete_batch(MatrixPins, MatrixPins.org_id == org_id, limit=limit)
        async with self._session_for(pins, org_id=org_id) as session:
            gone = deleted(await session.execute(pins))
            await session.commit()
        if gone >= limit:
            return gone
        choices = delete_batch(FillOverrides, FillOverrides.org_id == org_id, limit=limit - gone)
        async with self._session_for(choices, org_id=org_id) as session:
            gone += deleted(await session.execute(choices))
            await session.commit()
        return gone
