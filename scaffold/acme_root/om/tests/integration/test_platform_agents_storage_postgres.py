import pytest
from contracts.platform_agents_storage import PlatformAgentsStorageContract

from acme.om.platform_agents.storage import PlatformAgentsStorageInterface
from acme.om.platform_agents.storage.impl.postgres import PlatformAgentsStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestPlatformAgentsStoragePostgres(PlatformAgentsStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> PlatformAgentsStorageInterface:
        return PlatformAgentsStoragePostgresImpl(pg_sessions)
