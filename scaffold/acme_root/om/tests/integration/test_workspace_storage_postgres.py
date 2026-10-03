import pytest
from contracts.workspace_storage import RepositoryCredentialContract, WorkspaceStorageContract

from acme.om.storage.impl.pg_base import LoginSessions
from acme.om.workspaces.storage import WorkspaceStorageInterface
from acme.om.workspaces.storage.impl.postgres import WorkspaceStoragePostgresImpl

pytestmark = pytest.mark.integration


class TestWorkspaceStoragePostgres(WorkspaceStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> WorkspaceStorageInterface:
        return WorkspaceStoragePostgresImpl(pg_sessions)


class TestRepositoryCredentialsPostgres(RepositoryCredentialContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> WorkspaceStorageInterface:
        return WorkspaceStoragePostgresImpl(pg_sessions)
