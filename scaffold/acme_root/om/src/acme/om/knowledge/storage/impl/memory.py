from uuid import UUID

from acme.om.exceptions import PreconditionFailed
from acme.om.knowledge.storage import KnowledgeStorageInterface
from acme.om.knowledge.types.knowledge import Knowledge, KnowledgeStatus
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class KnowledgeStorageMemoryImpl(MemoryStorageBase, KnowledgeStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._entries: MemoryTable[Knowledge] = {}

    async def create_entry(
        self, org_id: UUID, entry: Knowledge, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            return self._insert(self._entries, org_id, entry, outbox_rows)

    async def read_entry(self, org_id: UUID, entry_id: UUID) -> Knowledge | None:
        return self._get(self._entries, org_id, entry_id)

    async def read_entries(
        self, org_id: UUID, status: KnowledgeStatus, after: UUID | None, limit: int
    ) -> list[Knowledge]:
        rows = [e for e in self._rows(self._entries, org_id) if e.status is status]
        return [e for e in rows if after is None or e.id > after][:limit]

    async def read_reachable(
        self, org_id: UUID, project_id: UUID | None, after: UUID | None, limit: int
    ) -> list[Knowledge]:
        rows = [
            e
            for e in self._rows(self._entries, org_id)
            if e.status is KnowledgeStatus.REVIEWED and e.project_id in (None, project_id)
        ]
        return sorted((e for e in rows if after is None or e.id > after), key=lambda e: e.id)[
            :limit
        ]

    async def read_by_slug(
        self, org_id: UUID, project_id: UUID | None, slug: str
    ) -> Knowledge | None:
        found = [
            e
            for e in self._rows(self._entries, org_id)
            if e.slug == slug
            and e.status is KnowledgeStatus.REVIEWED
            and e.project_id in (None, project_id)
        ]
        return min(found, key=lambda e: e.id) if found else None

    async def update_entry(
        self, org_id: UUID, entry: Knowledge, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        async with self._lock:
            held = self._get(self._entries, org_id, entry.id)
            if held is None or held.version + 1 != entry.version:
                raise PreconditionFailed(f"knowledge {entry.id} moved meanwhile")
            self._put(self._entries, org_id, entry, outbox_rows)

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            ids = [row.id for org, row in self._entries.values() if org == org_id][:limit]
            for row_id in ids:
                del self._entries[row_id]
            return len(ids)
