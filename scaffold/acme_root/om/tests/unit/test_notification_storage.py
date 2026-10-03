import pytest
from contracts.notification_storage import NotificationStorageContract

from acme.om.notifications.storage import NotificationStorageInterface
from acme.om.notifications.storage.impl.memory import NotificationStorageMemoryImpl


class TestNotificationStorageMemory(NotificationStorageContract):
    @pytest.fixture
    def storage(self) -> NotificationStorageInterface:
        return NotificationStorageMemoryImpl()
