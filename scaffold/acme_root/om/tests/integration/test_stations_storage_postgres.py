import pytest
from contracts.stations_storage import StationsStorageContract

from acme.om.stations.storage import StationsStorageInterface
from acme.om.stations.storage.impl.postgres import StationsStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestStationsStoragePostgres(StationsStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> StationsStorageInterface:
        return StationsStoragePostgresImpl(pg_sessions)
