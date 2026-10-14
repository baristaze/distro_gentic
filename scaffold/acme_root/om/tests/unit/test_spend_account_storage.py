import pytest
from contracts.account_storage import AccountStorageContract

from acme.om.billing.storage import AccountStorageInterface
from acme.om.billing.storage.impl.memory import AccountStorageMemoryImpl
from acme.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl


class TestAccountStorageMemory(AccountStorageContract):
    @pytest.fixture
    def storage(self) -> AccountStorageInterface:
        return AccountStorageMemoryImpl(OutboxStorageMemoryImpl())
