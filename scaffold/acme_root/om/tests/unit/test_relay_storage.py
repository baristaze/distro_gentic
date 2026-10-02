import pytest
from contracts.relay_storage import RelayStorageContract

from acme.om.relay.storage import RelayStorageInterface
from acme.om.relay.storage.impl.memory import RelayStorageMemoryImpl


class TestRelayStorageMemory(RelayStorageContract):
    @pytest.fixture
    def storage(self) -> RelayStorageInterface:
        return RelayStorageMemoryImpl()
