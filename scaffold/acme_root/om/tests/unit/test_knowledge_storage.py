import pytest
from contracts.knowledge_storage import KnowledgeStorageContract

from acme.om.knowledge.storage import KnowledgeStorageInterface
from acme.om.knowledge.storage.impl.memory import KnowledgeStorageMemoryImpl


class TestKnowledgeStorageMemory(KnowledgeStorageContract):
    @pytest.fixture
    def storage(self) -> KnowledgeStorageInterface:
        return KnowledgeStorageMemoryImpl()
