from uuid import UUID

from acme.om.exceptions import UniqueKeyTaken
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.playbooks.storage import PlaybookStorageInterface
from acme.om.playbooks.types.playbook import Playbook, PlaybookInvocation
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class PlaybookStorageMemoryImpl(MemoryStorageBase, PlaybookStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._playbooks: MemoryTable[Playbook] = {}
        self._invocations: MemoryTable[PlaybookInvocation] = {}

    async def create_playbook(
        self, org_id: UUID, playbook: Playbook, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            if playbook.id in self._playbooks:
                return False
            # One version of a name in a tenant: the unique index the table holds.
            if any(
                (p.name, p.version) == (playbook.name, playbook.version)
                for p in self._rows(self._playbooks, org_id)
            ):
                raise UniqueKeyTaken(f"playbooks {playbook.id}: the version is taken")
            return self._insert(self._playbooks, org_id, playbook, outbox_rows)

    async def read_playbook(self, org_id: UUID, playbook_id: UUID) -> Playbook | None:
        return self._get(self._playbooks, org_id, playbook_id)

    async def read_latest(self, org_id: UUID, name: str) -> Playbook | None:
        versions = [p for p in self._rows(self._playbooks, org_id) if p.name == name]
        return max(versions, key=lambda p: p.version, default=None)

    async def create_invocation(
        self, org_id: UUID, invocation: PlaybookInvocation
    ) -> PlaybookInvocation:
        async with self._lock:
            for held in self._rows(self._invocations, org_id):
                if (held.session_id, held.playbook_id) == (
                    invocation.session_id,
                    invocation.playbook_id,
                ):
                    return held
            self._put(self._invocations, org_id, invocation)
            return invocation

    async def read_invocations(
        self, org_id: UUID, session_id: UUID, limit: int
    ) -> list[PlaybookInvocation]:
        rows = [i for i in self._rows(self._invocations, org_id) if i.session_id == session_id]
        return sorted(rows, key=lambda i: (i.created_at, i.id))[:limit]

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            return _drop(self._playbooks, org_id, limit) + _drop(self._invocations, org_id, limit)


def _drop[E: Playbook | PlaybookInvocation](table: MemoryTable[E], org_id: UUID, limit: int) -> int:
    ids = [row.id for org, row in table.values() if org == org_id][:limit]
    for row_id in ids:
        del table[row_id]
    return len(ids)
