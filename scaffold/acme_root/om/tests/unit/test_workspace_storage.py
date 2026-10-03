import pytest
from contracts.workspace_storage import RepositoryCredentialContract, WorkspaceStorageContract

from acme.om.workspaces.storage import WorkspaceStorageInterface
from acme.om.workspaces.storage.impl.memory import WorkspaceStorageMemoryImpl


class TestWorkspaceStorageMemory(WorkspaceStorageContract):
    @pytest.fixture
    def storage(self) -> WorkspaceStorageInterface:
        return WorkspaceStorageMemoryImpl()


class TestRepositoryCredentialsMemory(RepositoryCredentialContract):
    @pytest.fixture
    def storage(self) -> WorkspaceStorageInterface:
        return WorkspaceStorageMemoryImpl()
