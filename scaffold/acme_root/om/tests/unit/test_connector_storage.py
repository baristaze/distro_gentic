import pytest

from acme.om.connectors.storage import ConnectorStorageInterface
from acme.om.connectors.storage.impl.memory import ConnectorStorageMemoryImpl

from contracts.connector_storage import ConnectorStorageContract


class TestConnectorStorageMemory(ConnectorStorageContract):
    @pytest.fixture
    def storage(self) -> ConnectorStorageInterface:
        return ConnectorStorageMemoryImpl()
