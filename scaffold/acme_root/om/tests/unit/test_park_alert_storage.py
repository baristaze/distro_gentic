import pytest
from contracts.park_alert_storage import ParkAlertStorageContract

from acme.om.park_alerts.storage import ParkAlertStorageInterface
from acme.om.park_alerts.storage.impl.memory import ParkAlertStorageMemoryImpl


class TestParkAlertStorageMemory(ParkAlertStorageContract):
    @pytest.fixture
    def storage(self) -> ParkAlertStorageInterface:
        return ParkAlertStorageMemoryImpl()
