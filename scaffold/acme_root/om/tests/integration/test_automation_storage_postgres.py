import pytest
from contracts.automation_storage import AutomationStorageContract

from acme.om.automations.storage import AutomationStorageInterface
from acme.om.automations.storage.impl.postgres import AutomationStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestAutomationStoragePostgres(AutomationStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> AutomationStorageInterface:
        return AutomationStoragePostgresImpl(pg_sessions)
