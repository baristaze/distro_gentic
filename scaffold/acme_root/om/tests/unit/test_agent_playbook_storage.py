import pytest

from acme.om.agent_playbooks.storage import AgentPlaybookStorageInterface
from acme.om.agent_playbooks.storage.impl.memory import AgentPlaybookStorageMemoryImpl

from contracts.agent_playbook_storage import AgentPlaybookStorageContract


class TestAgentPlaybookStorageMemory(AgentPlaybookStorageContract):
    @pytest.fixture
    def storage(self) -> AgentPlaybookStorageInterface:
        return AgentPlaybookStorageMemoryImpl()
