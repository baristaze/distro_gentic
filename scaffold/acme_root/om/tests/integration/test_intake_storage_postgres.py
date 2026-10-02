import pytest
from contracts.intake_storage import IntakeStorageContract

from acme.om.intake.storage import IntakeStorageInterface
from acme.om.intake.storage.impl.postgres import IntakeStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestIntakeStoragePostgres(IntakeStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> IntakeStorageInterface:
        return IntakeStoragePostgresImpl(pg_sessions)
