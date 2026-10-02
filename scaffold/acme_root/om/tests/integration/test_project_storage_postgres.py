import pytest
from contracts.project_storage import ProjectStorageContract

from acme.om.projects.storage import ProjectStorageInterface
from acme.om.projects.storage.impl.postgres import ProjectStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestProjectStoragePostgres(ProjectStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> ProjectStorageInterface:
        return ProjectStoragePostgresImpl(pg_sessions)
