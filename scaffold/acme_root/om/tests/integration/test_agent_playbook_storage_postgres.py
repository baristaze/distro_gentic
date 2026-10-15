import pytest

from acme.om.agent_playbooks.storage import AgentPlaybookStorageInterface
from acme.om.agent_playbooks.storage.impl.postgres import AgentPlaybookStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

from contracts.agent_playbook_storage import AgentPlaybookStorageContract

pytestmark = pytest.mark.integration


class TestAgentPlaybookStoragePostgres(AgentPlaybookStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> AgentPlaybookStorageInterface:
        return AgentPlaybookStoragePostgresImpl(pg_sessions)
