from uuid import UUID

from acme.om.agent_knowledge.storage import AgentKnowledgeStorageInterface
from acme.om.agent_knowledge.types.agent_knowledge import (
    AgentKnowledge,
    AgentKnowledgeRecall,
    AgentKnowledgeStatus,
)
from acme.om.exceptions import PreconditionFailed
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class AgentKnowledgeStorageMemoryImpl(MemoryStorageBase, AgentKnowledgeStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._entries: MemoryTable[AgentKnowledge] = {}
        self._recalls: MemoryTable[AgentKnowledgeRecall] = {}

    async def create_entry(
        self, org_id: UUID, entry: AgentKnowledge, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            return self._insert(self._entries, org_id, entry, outbox_rows)

    async def read_entry(self, org_id: UUID, entry_id: UUID) -> AgentKnowledge | None:
        return self._get(self._entries, org_id, entry_id)

    async def read_entries(
        self, org_id: UUID, status: AgentKnowledgeStatus, after: UUID | None, limit: int
    ) -> list[AgentKnowledge]:
        rows = [e for e in self._rows(self._entries, org_id) if e.status is status]
        return [e for e in rows if after is None or e.id > after][:limit]

    async def read_reachable(
        self, org_id: UUID, agent_project_id: UUID | None, after: UUID | None, limit: int
    ) -> list[AgentKnowledge]:
        rows = [
            e
            for e in self._rows(self._entries, org_id)
            if e.status is AgentKnowledgeStatus.REVIEWED
            and e.agent_project_id in (None, agent_project_id)
        ]
        return sorted((e for e in rows if after is None or e.id > after), key=lambda e: e.id)[
            :limit
        ]

    async def read_by_slug(
        self, org_id: UUID, agent_project_id: UUID | None, slug: str
    ) -> AgentKnowledge | None:
        found = [
            e
            for e in self._rows(self._entries, org_id)
            if e.slug == slug
            and e.status is AgentKnowledgeStatus.REVIEWED
            and e.agent_project_id in (None, agent_project_id)
        ]
        return min(found, key=lambda e: e.id) if found else None

    async def update_entry(
        self, org_id: UUID, entry: AgentKnowledge, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        async with self._lock:
            held = self._get(self._entries, org_id, entry.id)
            if held is None or held.version + 1 != entry.version:
                raise PreconditionFailed(f"agent knowledge {entry.id} moved meanwhile")
            self._put(self._entries, org_id, entry, outbox_rows)

    async def create_recalls(self, org_id: UUID, recalls: tuple[AgentKnowledgeRecall, ...]) -> None:
        async with self._lock:
            # One recall of an entry in a session: the unique index the table holds.
            held = {(r.agent_session_id, r.entry_id) for r in self._rows(self._recalls, org_id)}
            for recall in recalls:
                if (recall.agent_session_id, recall.entry_id) not in held:
                    self._put(self._recalls, org_id, recall)
                    held.add((recall.agent_session_id, recall.entry_id))

    async def read_recalls(
        self, org_id: UUID, agent_session_id: UUID, limit: int
    ) -> list[AgentKnowledgeRecall]:
        rows = [
            r for r in self._rows(self._recalls, org_id) if r.agent_session_id == agent_session_id
        ]
        return sorted(rows, key=lambda r: (r.created_at, r.id))[:limit]

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            return _drop(self._recalls, org_id, limit) + _drop(self._entries, org_id, limit)


def _drop[E: AgentKnowledge | AgentKnowledgeRecall](
    table: MemoryTable[E], org_id: UUID, limit: int
) -> int:
    ids = [row.id for org, row in table.values() if org == org_id][:limit]
    for row_id in ids:
        del table[row_id]
    return len(ids)
