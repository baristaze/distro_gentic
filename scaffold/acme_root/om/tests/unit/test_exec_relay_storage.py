import pytest
from contracts.exec_relay_storage import ExecRelayStorageContract

from acme.om.exec_relay.storage import ExecRelayStorageInterface
from acme.om.exec_relay.storage.impl.memory import ExecRelayStorageMemoryImpl


class TestRelayStorageMemory(ExecRelayStorageContract):
    @pytest.fixture
    def storage(self) -> ExecRelayStorageInterface:
        return ExecRelayStorageMemoryImpl()
