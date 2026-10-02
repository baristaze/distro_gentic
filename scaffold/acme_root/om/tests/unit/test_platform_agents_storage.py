import pytest
from contracts.platform_agents_storage import PlatformAgentsStorageContract

from acme.om.platform_agents.storage import PlatformAgentsStorageInterface
from acme.om.platform_agents.storage.impl.memory import PlatformAgentsStorageMemoryImpl


class TestPlatformAgentsStorageMemory(PlatformAgentsStorageContract):
    @pytest.fixture
    def storage(self) -> PlatformAgentsStorageInterface:
        return PlatformAgentsStorageMemoryImpl()
