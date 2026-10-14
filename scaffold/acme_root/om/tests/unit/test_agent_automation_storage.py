import pytest
from contracts.agent_automation_storage import AgentAutomationStorageContract

from acme.om.agent_automations.storage import AgentAutomationStorageInterface
from acme.om.agent_automations.storage.impl.memory import AgentAutomationStorageMemoryImpl


class TestAgentAutomationStorageMemory(AgentAutomationStorageContract):
    @pytest.fixture
    def storage(self) -> AgentAutomationStorageInterface:
        return AgentAutomationStorageMemoryImpl()
