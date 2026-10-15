import pytest

from acme.om.exec_relay.storage import ExecRelayStorageInterface
from acme.om.exec_relay.storage.impl.memory import ExecRelayStorageMemoryImpl

from contracts.exec_relay_storage import ExecRelayStorageContract


class TestRelayStorageMemory(ExecRelayStorageContract):
    @pytest.fixture
    def storage(self) -> ExecRelayStorageInterface:
        return ExecRelayStorageMemoryImpl()
