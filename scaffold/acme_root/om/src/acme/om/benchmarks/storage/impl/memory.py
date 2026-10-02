from uuid import UUID

from acme.om.base import EMPTY_UUID
from acme.om.benchmarks.storage import BenchmarkStorageInterface
from acme.om.benchmarks.types.benchmark import Benchmark
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class BenchmarkStorageMemoryImpl(MemoryStorageBase, BenchmarkStorageInterface):
    """The global rows under the system scope's id, as no tenant's."""

    def __init__(self) -> None:
        super().__init__()
        self._benchmarks: MemoryTable[Benchmark] = {}

    async def create_benchmark(self, benchmark: Benchmark) -> bool:
        async with self._lock:
            if self._get(self._benchmarks, EMPTY_UUID, benchmark.id) is not None:
                return False
            self._insert(self._benchmarks, EMPTY_UUID, benchmark)
            return True

    async def read_benchmark(self, benchmark_id: UUID) -> Benchmark | None:
        return self._get(self._benchmarks, EMPTY_UUID, benchmark_id)

    async def read_history(self, scenario: str, limit: int) -> list[Benchmark]:
        found = [b for b in self._every(self._benchmarks) if b.scenario == scenario]
        found.sort(key=lambda b: (b.created_at, b.id), reverse=True)
        return found[:limit]
