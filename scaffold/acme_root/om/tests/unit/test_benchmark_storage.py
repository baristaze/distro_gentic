import pytest

from acme.om.benchmarks.storage import BenchmarkStorageInterface
from acme.om.benchmarks.storage.impl.memory import BenchmarkStorageMemoryImpl

from contracts.benchmark_storage import BenchmarkStorageContract


class TestBenchmarkStorageMemory(BenchmarkStorageContract):
    @pytest.fixture
    def storage(self) -> BenchmarkStorageInterface:
        return BenchmarkStorageMemoryImpl()
