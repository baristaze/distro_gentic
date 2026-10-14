import pytest
from contracts.agent_playbook_storage import AgentPlaybookStorageContract

from acme.om.agent_playbooks.storage import AgentPlaybookStorageInterface
from acme.om.agent_playbooks.storage.impl.postgres import AgentPlaybookStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestAgentPlaybookStoragePostgres(AgentPlaybookStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> AgentPlaybookStorageInterface:
        return AgentPlaybookStoragePostgresImpl(pg_sessions)
