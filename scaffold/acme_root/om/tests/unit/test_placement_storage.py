import pytest
from contracts.placement_storage import PlacementStorageContract

from acme.om.placement.storage import PlacementStorageInterface
from acme.om.placement.storage.impl.memory import PlacementStorageMemoryImpl


class TestPlacementStorageMemory(PlacementStorageContract):
    @pytest.fixture
    def storage(self) -> PlacementStorageInterface:
        return PlacementStorageMemoryImpl()
