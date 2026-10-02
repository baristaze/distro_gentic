import pytest
from contracts.knowledge_storage import KnowledgeStorageContract

from acme.om.knowledge.storage import KnowledgeStorageInterface
from acme.om.knowledge.storage.impl.postgres import KnowledgeStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestKnowledgeStoragePostgres(KnowledgeStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> KnowledgeStorageInterface:
        return KnowledgeStoragePostgresImpl(pg_sessions)
