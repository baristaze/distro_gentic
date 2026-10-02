import pytest
from contracts.playbook_storage import PlaybookStorageContract

from acme.om.playbooks.storage import PlaybookStorageInterface
from acme.om.playbooks.storage.impl.memory import PlaybookStorageMemoryImpl


class TestPlaybookStorageMemory(PlaybookStorageContract):
    @pytest.fixture
    def storage(self) -> PlaybookStorageInterface:
        return PlaybookStorageMemoryImpl()
