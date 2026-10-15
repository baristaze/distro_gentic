import pytest

from acme.om.agent_workspaces.storage import AgentWorkspaceStorageInterface
from acme.om.agent_workspaces.storage.impl.postgres import AgentWorkspaceStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

from contracts.agent_workspace_storage import (
    AgentWorkspaceStorageContract,
    RepositoryCredentialContract,
)

pytestmark = pytest.mark.integration


class TestAgentWorkspaceStoragePostgres(AgentWorkspaceStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> AgentWorkspaceStorageInterface:
        return AgentWorkspaceStoragePostgresImpl(pg_sessions)


class TestRepositoryCredentialsPostgres(RepositoryCredentialContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> AgentWorkspaceStorageInterface:
        return AgentWorkspaceStoragePostgresImpl(pg_sessions)
