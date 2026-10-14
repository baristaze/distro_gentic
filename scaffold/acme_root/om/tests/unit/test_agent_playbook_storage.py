import pytest
from contracts.agent_playbook_storage import AgentPlaybookStorageContract

from acme.om.agent_playbooks.storage import AgentPlaybookStorageInterface
from acme.om.agent_playbooks.storage.impl.memory import AgentPlaybookStorageMemoryImpl


class TestAgentPlaybookStorageMemory(AgentPlaybookStorageContract):
    @pytest.fixture
    def storage(self) -> AgentPlaybookStorageInterface:
        return AgentPlaybookStorageMemoryImpl()
