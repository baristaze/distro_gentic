import pytest

from acme.om.hosts.storage import HostsStorageInterface
from acme.om.hosts.storage.impl.postgres import HostsStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

from contracts.hosts_storage import HostsStorageContract

pytestmark = pytest.mark.integration


class TestHostsStoragePostgres(HostsStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> HostsStorageInterface:
        return HostsStoragePostgresImpl(pg_sessions)
