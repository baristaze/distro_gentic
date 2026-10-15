import pytest

from acme.om.agent_automations.storage import AgentAutomationStorageInterface
from acme.om.agent_automations.storage.impl.postgres import AgentAutomationStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

from contracts.agent_automation_storage import AgentAutomationStorageContract

pytestmark = pytest.mark.integration


class TestAgentAutomationStoragePostgres(AgentAutomationStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> AgentAutomationStorageInterface:
        return AgentAutomationStoragePostgresImpl(pg_sessions)
