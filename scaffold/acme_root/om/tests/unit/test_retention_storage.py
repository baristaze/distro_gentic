import pytest

from acme.om.retention.storage import RetentionStorageInterface
from acme.om.retention.storage.impl.memory import RetentionStorageMemoryImpl

from contracts.retention_storage import RetentionStorageContract


class TestRetentionStorageMemory(RetentionStorageContract):
    @pytest.fixture
    def storage(self) -> RetentionStorageInterface:
        return RetentionStorageMemoryImpl()
