import pytest

from acme.om.agent_workspaces.storage import AgentWorkspaceStorageInterface
from acme.om.agent_workspaces.storage.impl.memory import AgentWorkspaceStorageMemoryImpl

from contracts.agent_workspace_storage import (
    AgentWorkspaceStorageContract,
    RepositoryCredentialContract,
)


class TestAgentWorkspaceStorageMemory(AgentWorkspaceStorageContract):
    @pytest.fixture
    def storage(self) -> AgentWorkspaceStorageInterface:
        return AgentWorkspaceStorageMemoryImpl()


class TestRepositoryCredentialsMemory(RepositoryCredentialContract):
    @pytest.fixture
    def storage(self) -> AgentWorkspaceStorageInterface:
        return AgentWorkspaceStorageMemoryImpl()
