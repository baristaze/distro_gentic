import pytest
from contracts.retention_storage import RetentionStorageContract

from acme.om.retention.storage import RetentionStorageInterface
from acme.om.retention.storage.impl.memory import RetentionStorageMemoryImpl


class TestRetentionStorageMemory(RetentionStorageContract):
    @pytest.fixture
    def storage(self) -> RetentionStorageInterface:
        return RetentionStorageMemoryImpl()
