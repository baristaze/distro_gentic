import pytest
from contracts.trust_storage import TrustStorageContract

from acme.om.trust.storage import TrustStorageInterface
from acme.om.trust.storage.impl.memory import TrustStorageMemoryImpl


class TestTrustStorageMemory(TrustStorageContract):
    @pytest.fixture
    def storage(self) -> TrustStorageInterface:
        return TrustStorageMemoryImpl()
