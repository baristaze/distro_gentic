import pytest

from acme.om.agent_knowledge.storage import AgentKnowledgeStorageInterface
from acme.om.agent_knowledge.storage.impl.memory import AgentKnowledgeStorageMemoryImpl

from contracts.agent_knowledge_storage import AgentKnowledgeStorageContract


class TestAgentKnowledgeStorageMemory(AgentKnowledgeStorageContract):
    @pytest.fixture
    def storage(self) -> AgentKnowledgeStorageInterface:
        return AgentKnowledgeStorageMemoryImpl()
