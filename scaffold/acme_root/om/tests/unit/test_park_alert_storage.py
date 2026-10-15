import pytest

from acme.om.park_alerts.storage import ParkAlertStorageInterface
from acme.om.park_alerts.storage.impl.memory import ParkAlertStorageMemoryImpl

from contracts.park_alert_storage import ParkAlertStorageContract


class TestParkAlertStorageMemory(ParkAlertStorageContract):
    @pytest.fixture
    def storage(self) -> ParkAlertStorageInterface:
        return ParkAlertStorageMemoryImpl()
