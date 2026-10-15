import pytest

from acme.om.hosts.storage import HostsStorageInterface
from acme.om.hosts.storage.impl.memory import HostsStorageMemoryImpl

from contracts.hosts_storage import HostsStorageContract


class TestHostsStorageMemory(HostsStorageContract):
    @pytest.fixture
    def storage(self) -> HostsStorageInterface:
        return HostsStorageMemoryImpl()
