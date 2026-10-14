"""The platform's case of the ledger contract, over the memory impl."""

import pytest
from contracts.platform_ledger_storage import PlatformLedgerStorageContract

from acme.om.budgets.storage import LedgerStorageInterface
from acme.om.budgets.storage.impl.memory import LedgerStorageMemoryImpl


class TestPlatformLedgerStorageMemory(PlatformLedgerStorageContract):
    @pytest.fixture
    def storage(self) -> LedgerStorageInterface:
        return LedgerStorageMemoryImpl()
