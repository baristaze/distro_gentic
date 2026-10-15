import pytest

from acme.om.platform_agents.storage import PlatformAgentsStorageInterface
from acme.om.platform_agents.storage.impl.memory import PlatformAgentsStorageMemoryImpl

from contracts.platform_agents_storage import PlatformAgentsStorageContract


class TestPlatformAgentsStorageMemory(PlatformAgentsStorageContract):
    @pytest.fixture
    def storage(self) -> PlatformAgentsStorageInterface:
        return PlatformAgentsStorageMemoryImpl()
