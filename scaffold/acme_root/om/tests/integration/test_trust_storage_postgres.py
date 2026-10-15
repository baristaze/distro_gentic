import pytest

from acme.om.storage.impl.pg_base import LoginSessions
from acme.om.trust.storage import TrustStorageInterface
from acme.om.trust.storage.impl.postgres import TrustStoragePostgresImpl

from contracts.trust_storage import TrustStorageContract

pytestmark = pytest.mark.integration


class TestTrustStoragePostgres(TrustStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> TrustStorageInterface:
        return TrustStoragePostgresImpl(pg_sessions)
