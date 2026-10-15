"""The platform's cases of the work storage contract, over the memory impl."""

import pytest

from acme.om.work.storage import WorkStorageInterface
from acme.om.work.storage.impl.memory import WorkStorageMemoryImpl

from contracts.platform_work_storage import PlatformWorkStorageContract


class TestPlatformWorkStorageMemory(PlatformWorkStorageContract):
    @pytest.fixture
    def storage(self) -> WorkStorageInterface:
        return WorkStorageMemoryImpl()
