import pytest

from acme.om.agent_knowledge.storage import AgentKnowledgeStorageInterface
from acme.om.agent_knowledge.storage.impl.postgres import AgentKnowledgeStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

from contracts.agent_knowledge_storage import AgentKnowledgeStorageContract

pytestmark = pytest.mark.integration


class TestAgentKnowledgeStoragePostgres(AgentKnowledgeStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> AgentKnowledgeStorageInterface:
        return AgentKnowledgeStoragePostgresImpl(pg_sessions)
