"""The platform's case of the ledger contract, over Postgres."""

import pytest
from contracts.platform_ledger_storage import PlatformLedgerStorageContract

from acme.om.budgets.storage import LedgerStorageInterface
from acme.om.budgets.storage.impl.postgres import LedgerStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestPlatformLedgerStoragePostgres(PlatformLedgerStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> LedgerStorageInterface:
        return LedgerStoragePostgresImpl(pg_sessions)
