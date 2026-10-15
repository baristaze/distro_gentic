import pytest

from acme.om.connectors.storage import ConnectorStorageInterface
from acme.om.connectors.storage.impl.postgres import ConnectorStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

from contracts.connector_storage import ConnectorStorageContract

pytestmark = pytest.mark.integration


class TestConnectorStoragePostgres(ConnectorStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> ConnectorStorageInterface:
        return ConnectorStoragePostgresImpl(pg_sessions)
