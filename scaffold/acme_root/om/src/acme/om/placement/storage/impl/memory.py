from uuid import UUID

from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.placement.storage import PlacementStorageInterface, ShareToCarry
from acme.om.placement.types.share import FairShare
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class PlacementStorageMemoryImpl(MemoryStorageBase, PlacementStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._shares: MemoryTable[FairShare] = {}
        # The concurrency of each share still to carry, by its id.
        self._uncarried: dict[UUID, int] = {}

    def written_before(self, org_id: UUID, share: FairShare, concurrency: int) -> None:
        """The twin of a share the release before wrote, with the concurrency
        it held: what the sweep carries. Nothing this release runs writes
        one, so only a case does."""
        self._insert(self._shares, org_id, share)
        self._uncarried[share.id] = concurrency

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
            self._uncarried.pop(share.id, None)

    async def read_uncarried(self, limit: int) -> list[ShareToCarry]:
        return [
            ShareToCarry(org_id=org_id, share=share, concurrency=self._uncarried[share.id])
            for org_id, share in self._rows_across_tenants(self._shares)
            if share.id in self._uncarried
        ][:limit]

    async def mark_carried(self, org_id: UUID, share_id: UUID) -> bool:
        async with self._lock:
            if self._get(self._shares, org_id, share_id) is None:
                return False
            return self._uncarried.pop(share_id, None) is not None

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            gone = [share.id for share in self._rows(self._shares, org_id)][:limit]
            for share_id in gone:
                del self._shares[share_id]
                self._uncarried.pop(share_id, None)
            return len(gone)
