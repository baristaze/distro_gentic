import pytest
from contracts.agent_knowledge_storage import AgentKnowledgeStorageContract

from acme.om.agent_knowledge.storage import AgentKnowledgeStorageInterface
from acme.om.agent_knowledge.storage.impl.memory import AgentKnowledgeStorageMemoryImpl


class TestAgentKnowledgeStorageMemory(AgentKnowledgeStorageContract):
    @pytest.fixture
    def storage(self) -> AgentKnowledgeStorageInterface:
        return AgentKnowledgeStorageMemoryImpl()
