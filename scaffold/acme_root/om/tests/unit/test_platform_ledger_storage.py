"""The platform's case of the ledger contract, over the memory impl."""

import pytest

from acme.om.spend_budgets.storage import LedgerStorageInterface
from acme.om.spend_budgets.storage.impl.memory import LedgerStorageMemoryImpl

from contracts.platform_ledger_storage import PlatformLedgerStorageContract


class TestPlatformLedgerStorageMemory(PlatformLedgerStorageContract):
    @pytest.fixture
    def storage(self) -> LedgerStorageInterface:
        return LedgerStorageMemoryImpl()
