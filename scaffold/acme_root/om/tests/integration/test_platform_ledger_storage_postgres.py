"""The platform's case of the ledger contract, over Postgres."""

import pytest

from acme.om.spend_budgets.storage import LedgerStorageInterface
from acme.om.spend_budgets.storage.impl.postgres import LedgerStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

from contracts.platform_ledger_storage import PlatformLedgerStorageContract

pytestmark = pytest.mark.integration


class TestPlatformLedgerStoragePostgres(PlatformLedgerStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> LedgerStorageInterface:
        return LedgerStoragePostgresImpl(pg_sessions)
