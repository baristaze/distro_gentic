import pytest
from contracts.agent_project_storage import AgentProjectStorageContract

from acme.om.agent_projects.storage import AgentProjectStorageInterface
from acme.om.agent_projects.storage.impl.postgres import AgentProjectStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestAgentProjectStoragePostgres(AgentProjectStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> AgentProjectStorageInterface:
        return AgentProjectStoragePostgresImpl(pg_sessions)
