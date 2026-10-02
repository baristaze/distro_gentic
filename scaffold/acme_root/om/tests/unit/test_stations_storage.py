import pytest
from contracts.stations_storage import StationsStorageContract

from acme.om.stations.storage import StationsStorageInterface
from acme.om.stations.storage.impl.memory import StationsStorageMemoryImpl


class TestStationsStorageMemory(StationsStorageContract):
    @pytest.fixture
    def storage(self) -> StationsStorageInterface:
        return StationsStorageMemoryImpl()
