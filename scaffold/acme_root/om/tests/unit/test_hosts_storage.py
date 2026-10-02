import pytest
from contracts.hosts_storage import HostsStorageContract

from acme.om.hosts.storage import HostsStorageInterface
from acme.om.hosts.storage.impl.memory import HostsStorageMemoryImpl


class TestHostsStorageMemory(HostsStorageContract):
    @pytest.fixture
    def storage(self) -> HostsStorageInterface:
        return HostsStorageMemoryImpl()
