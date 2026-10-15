import pytest

from acme.om.park_alerts.storage import ParkAlertStorageInterface
from acme.om.park_alerts.storage.impl.postgres import ParkAlertStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

from contracts.park_alert_storage import ParkAlertStorageContract

pytestmark = pytest.mark.integration


class TestParkAlertStoragePostgres(ParkAlertStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> ParkAlertStorageInterface:
        return ParkAlertStoragePostgresImpl(pg_sessions)
