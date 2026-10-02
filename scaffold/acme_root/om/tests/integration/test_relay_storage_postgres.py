import pytest
from contracts.relay_storage import RelayStorageContract

from acme.om.relay.storage import RelayStorageInterface
from acme.om.relay.storage.impl.postgres import RelayStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestRelayStoragePostgres(RelayStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> RelayStorageInterface:
        return RelayStoragePostgresImpl(pg_sessions)
