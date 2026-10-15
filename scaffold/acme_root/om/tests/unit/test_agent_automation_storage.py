import pytest

from acme.om.agent_automations.storage import AgentAutomationStorageInterface
from acme.om.agent_automations.storage.impl.memory import AgentAutomationStorageMemoryImpl

from contracts.agent_automation_storage import AgentAutomationStorageContract


class TestAgentAutomationStorageMemory(AgentAutomationStorageContract):
    @pytest.fixture
    def storage(self) -> AgentAutomationStorageInterface:
        return AgentAutomationStorageMemoryImpl()
