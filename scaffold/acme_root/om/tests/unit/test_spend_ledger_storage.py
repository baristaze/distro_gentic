import pytest

from acme.om.agent_billing.storage import SpendLedgerStorageInterface
from acme.om.agent_billing.storage.impl.memory import SpendLedgerStorageMemoryImpl

from contracts.spend_ledger_storage import SpendLedgerStorageContract


class TestSpendLedgerStorageMemory(SpendLedgerStorageContract):
    @pytest.fixture
    def storage(self) -> SpendLedgerStorageInterface:
        return SpendLedgerStorageMemoryImpl()
