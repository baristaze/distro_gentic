"""Storage of the benchmarks swimlane. A benchmark is one row in `core`,
of the system scope and no tenant's, written once: the serving logins hold
SELECT and INSERT on it, and nothing rewrites or deletes what a run
showed."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.benchmarks.types.benchmark import Benchmark


class BenchmarkStorageInterface(ABC):
    @abstractmethod
    async def create_benchmark(self, benchmark: Benchmark) -> bool:
        """Global: one benchmark, no tenant's; False, with nothing written,
        when its id is written already."""
        ...

    @abstractmethod
    async def read_benchmark(self, benchmark_id: UUID) -> Benchmark | None:
        """Global: one benchmark, or None when there is none by that id."""
        ...

    @abstractmethod
    async def read_history(self, scenario: str, limit: int) -> list[Benchmark]:
        """Global: the scenario's benchmarks, the newest first, at most
        `limit`."""
        ...
