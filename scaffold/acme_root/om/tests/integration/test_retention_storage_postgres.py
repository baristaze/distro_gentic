import pytest

from acme.om.retention.storage import RetentionStorageInterface
from acme.om.retention.storage.impl.postgres import RetentionStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

from contracts.retention_storage import RetentionStorageContract

pytestmark = pytest.mark.integration


class TestRetentionStoragePostgres(RetentionStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> RetentionStorageInterface:
        return RetentionStoragePostgresImpl(pg_sessions)
