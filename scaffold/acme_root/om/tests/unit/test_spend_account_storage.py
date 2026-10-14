import pytest
from contracts.spend_account_storage import SpendAccountStorageContract

from acme.om.agent_billing.storage import SpendAccountStorageInterface
from acme.om.agent_billing.storage.impl.memory import SpendAccountStorageMemoryImpl
from acme.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl


class TestAccountStorageMemory(SpendAccountStorageContract):
    @pytest.fixture
    def storage(self) -> SpendAccountStorageInterface:
        return SpendAccountStorageMemoryImpl(OutboxStorageMemoryImpl())
