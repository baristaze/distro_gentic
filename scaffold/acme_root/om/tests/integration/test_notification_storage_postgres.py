import pytest
from contracts.notification_storage import NotificationStorageContract

from acme.om.notifications.storage import NotificationStorageInterface
from acme.om.notifications.storage.impl.postgres import NotificationStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestNotificationStoragePostgres(NotificationStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> NotificationStorageInterface:
        return NotificationStoragePostgresImpl(pg_sessions)
