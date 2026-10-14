import pytest
from contracts.exec_relay_storage import ExecRelayStorageContract

from acme.om.exec_relay.storage import ExecRelayStorageInterface
from acme.om.exec_relay.storage.impl.postgres import ExecRelayStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestRelayStoragePostgres(ExecRelayStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> ExecRelayStorageInterface:
        return ExecRelayStoragePostgresImpl(pg_sessions)
