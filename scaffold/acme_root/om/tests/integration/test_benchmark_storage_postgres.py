import pytest

from acme.om.benchmarks.storage import BenchmarkStorageInterface
from acme.om.benchmarks.storage.impl.postgres import BenchmarkStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

from contracts.benchmark_storage import BenchmarkStorageContract

pytestmark = pytest.mark.integration


class TestBenchmarkStoragePostgres(BenchmarkStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> BenchmarkStorageInterface:
        return BenchmarkStoragePostgresImpl(pg_sessions)
