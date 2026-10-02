from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from acme.om.base import EMPTY_UUID
from acme.om.benchmarks.storage import BenchmarkStorageInterface
from acme.om.benchmarks.storage.tables.benchmarks import Benchmarks
from acme.om.benchmarks.types.benchmark import Benchmark
from acme.om.storage.impl.pg_base import PgStorageBase
from acme.om.storage.utils.translation import to_model, to_values


class BenchmarkStoragePostgresImpl(PgStorageBase, BenchmarkStorageInterface):
    """The global rows, each statement in the system scope (`EMPTY_UUID`):
    the table carries no policy, and no tenant names it."""

    async def create_benchmark(self, benchmark: Benchmark) -> bool:
        stmt = (
            insert(Benchmarks)
            .values(**to_values(benchmark, Benchmarks))
            .on_conflict_do_nothing(index_elements=[Benchmarks.id])
            .returning(Benchmarks.id)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            landed = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
            return landed is not None

    async def read_benchmark(self, benchmark_id: UUID) -> Benchmark | None:
        stmt = select(Benchmarks).where(Benchmarks.id == benchmark_id)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Benchmark)

    async def read_history(self, scenario: str, limit: int) -> list[Benchmark]:
        stmt = (
            select(Benchmarks)
            .where(Benchmarks.scenario == scenario)
            .order_by(Benchmarks.created_at.desc(), Benchmarks.id.desc())
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            rows = (await session.execute(stmt)).scalars()
            return [to_model(row, Benchmark) for row in rows]
