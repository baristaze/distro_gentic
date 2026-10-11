import pytest
from contracts.cloud_pool_storage import CloudPoolStorageContract

from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.storage.impl.memory import CloudPoolStorageMemoryImpl


class TestCloudPoolStorageMemory(CloudPoolStorageContract):
    @pytest.fixture
    def storage(self) -> CloudPoolStorageInterface:
        return CloudPoolStorageMemoryImpl()
