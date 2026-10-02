import pytest
from contracts.project_storage import ProjectStorageContract

from acme.om.projects.storage import ProjectStorageInterface
from acme.om.projects.storage.impl.memory import ProjectStorageMemoryImpl


class TestProjectStorageMemory(ProjectStorageContract):
    @pytest.fixture
    def storage(self) -> ProjectStorageInterface:
        return ProjectStorageMemoryImpl()
