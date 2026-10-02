from uuid import UUID

from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.placement.storage import PlacementStorageInterface
from acme.om.placement.types.share import FairShare
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class PlacementStorageMemoryImpl(MemoryStorageBase, PlacementStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._shares: MemoryTable[FairShare] = {}

    async def read_share(self, org_id: UUID) -> FairShare | None:
        found = self._rows(self._shares, org_id)
        return found[0] if found else None

    async def create_share(self, org_id: UUID, share: FairShare) -> bool:
        async with self._lock:
            if share.id in self._shares:
                return False
            # One share a tenant: the unique index the table holds.
            if self._rows(self._shares, org_id):
                raise UniqueKeyTaken(f"fair_shares {share.id}: the tenant holds a share")
            return self._insert(self._shares, org_id, share)

    async def write_share(self, org_id: UUID, share: FairShare, expected_version: int) -> None:
        async with self._lock:
            found = self._get(self._shares, org_id, share.id)
            if found is None or found.version != expected_version:
                raise PreconditionFailed(
                    f"fair share {share.id} is no longer at version {expected_version}"
                )
            self._put(self._shares, org_id, share)

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            gone = [share.id for share in self._rows(self._shares, org_id)][:limit]
            for share_id in gone:
                del self._shares[share_id]
            return len(gone)
