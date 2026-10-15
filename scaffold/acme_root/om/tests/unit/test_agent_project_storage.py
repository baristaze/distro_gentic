import pytest

from acme.om.agent_projects.storage import AgentProjectStorageInterface
from acme.om.agent_projects.storage.impl.memory import AgentProjectStorageMemoryImpl

from contracts.agent_project_storage import AgentProjectStorageContract


class TestAgentProjectStorageMemory(AgentProjectStorageContract):
    @pytest.fixture
    def storage(self) -> AgentProjectStorageInterface:
        return AgentProjectStorageMemoryImpl()
