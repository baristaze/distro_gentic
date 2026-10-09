from uuid import UUID

import pytest
from contracts.placement_storage import PlacementStorageContract, WrittenBefore

from acme.om.placement.storage import PlacementStorageInterface
from acme.om.placement.storage.impl.memory import PlacementStorageMemoryImpl
from acme.om.placement.types.share import FairShare


class TestPlacementStorageMemory(PlacementStorageContract):
    @pytest.fixture
    def storage(self) -> PlacementStorageInterface:
        return PlacementStorageMemoryImpl()

    @pytest.fixture
    def written_before(self, storage: PlacementStorageInterface) -> WrittenBefore:
        assert isinstance(storage, PlacementStorageMemoryImpl)

        async def write(org_id: UUID, share: FairShare, concurrency: int) -> None:
            storage.written_before(org_id, share, concurrency)

        return write
