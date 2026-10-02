import pytest
from contracts.automation_storage import AutomationStorageContract

from acme.om.automations.storage import AutomationStorageInterface
from acme.om.automations.storage.impl.memory import AutomationStorageMemoryImpl


class TestAutomationStorageMemory(AutomationStorageContract):
    @pytest.fixture
    def storage(self) -> AutomationStorageInterface:
        return AutomationStorageMemoryImpl()
