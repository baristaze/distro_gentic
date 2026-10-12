from uuid import UUID

from acme.om.exceptions import UniqueKeyTaken
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.playbooks.storage import PlaybookStorageInterface
from acme.om.playbooks.types.playbook import Playbook, PlaybookInvocation, PlaybookPin
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class PlaybookStorageMemoryImpl(MemoryStorageBase, PlaybookStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._playbooks: MemoryTable[Playbook] = {}
        self._invocations: MemoryTable[PlaybookInvocation] = {}
        self._pins: MemoryTable[PlaybookPin] = {}

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

    async def put_pin(
        self, org_id: UUID, pin: PlaybookPin, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        async with self._lock:
            # One pin a kind and a project in a tenant, the tenant's own among
            # them: the unique index the table holds, its nulls not distinct.
            if any(
                (held.kind, held.project_id) == (pin.kind, pin.project_id) and held.id != pin.id
                for held in self._rows(self._pins, org_id)
            ):
                raise UniqueKeyTaken(f"playbook_pins {pin.id}: the kind is pinned")
            self._put(self._pins, org_id, pin, outbox_rows)

    async def read_pin(
        self, org_id: UUID, kind: str, project_id: UUID | None
    ) -> PlaybookPin | None:
        for held in self._rows(self._pins, org_id):
            if (held.kind, held.project_id) == (kind, project_id):
                return held
        return None

    async def read_pins(self, org_id: UUID, limit: int) -> list[PlaybookPin]:
        rows = self._rows(self._pins, org_id)
        return sorted(rows, key=lambda p: (p.kind, p.project_id is not None, str(p.project_id)))[
            :limit
        ]

    async def delete_pin(
        self, org_id: UUID, pin_id: UUID, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            if self._get(self._pins, org_id, pin_id) is None:
                return False
            self._land(org_id, outbox_rows)
            del self._pins[pin_id]
            return True

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            return (
                _drop(self._playbooks, org_id, limit)
                + _drop(self._invocations, org_id, limit)
                + _drop(self._pins, org_id, limit)
            )


def _drop[E: Playbook | PlaybookInvocation | PlaybookPin](
    table: MemoryTable[E], org_id: UUID, limit: int
) -> int:
    ids = [row.id for org, row in table.values() if org == org_id][:limit]
    for row_id in ids:
        del table[row_id]
    return len(ids)
