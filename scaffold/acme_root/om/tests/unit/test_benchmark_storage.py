import pytest
from contracts.benchmark_storage import BenchmarkStorageContract

from acme.om.benchmarks.storage import BenchmarkStorageInterface
from acme.om.benchmarks.storage.impl.memory import BenchmarkStorageMemoryImpl


class TestBenchmarkStorageMemory(BenchmarkStorageContract):
    @pytest.fixture
    def storage(self) -> BenchmarkStorageInterface:
        return BenchmarkStorageMemoryImpl()
