import pytest
from contracts.retention_storage import RetentionStorageContract

from acme.om.retention.storage import RetentionStorageInterface
from acme.om.retention.storage.impl.postgres import RetentionStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestRetentionStoragePostgres(RetentionStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> RetentionStorageInterface:
        return RetentionStoragePostgresImpl(pg_sessions)
