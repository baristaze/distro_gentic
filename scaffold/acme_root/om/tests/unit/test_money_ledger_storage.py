import pytest
from contracts.money_ledger_storage import MoneyLedgerStorageContract

from acme.om.billing.storage import MoneyLedgerStorageInterface
from acme.om.billing.storage.impl.memory import MoneyLedgerStorageMemoryImpl


class TestMoneyLedgerStorageMemory(MoneyLedgerStorageContract):
    @pytest.fixture
    def storage(self) -> MoneyLedgerStorageInterface:
        return MoneyLedgerStorageMemoryImpl()
