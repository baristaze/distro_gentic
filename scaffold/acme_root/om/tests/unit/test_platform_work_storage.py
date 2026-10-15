"""The platform's cases of the work storage contract, over the memory impl."""

import pytest
from contracts.platform_work_storage import PlatformWorkStorageContract

from acme.om.work.storage import WorkStorageInterface
from acme.om.work.storage.impl.memory import WorkStorageMemoryImpl


class TestPlatformWorkStorageMemory(PlatformWorkStorageContract):
    @pytest.fixture
    def storage(self) -> WorkStorageInterface:
        return WorkStorageMemoryImpl()
