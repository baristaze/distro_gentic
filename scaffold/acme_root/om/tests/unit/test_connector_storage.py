import pytest
from contracts.connector_storage import ConnectorStorageContract

from acme.om.connectors.storage import ConnectorStorageInterface
from acme.om.connectors.storage.impl.memory import ConnectorStorageMemoryImpl


class TestConnectorStorageMemory(ConnectorStorageContract):
    @pytest.fixture
    def storage(self) -> ConnectorStorageInterface:
        return ConnectorStorageMemoryImpl()
