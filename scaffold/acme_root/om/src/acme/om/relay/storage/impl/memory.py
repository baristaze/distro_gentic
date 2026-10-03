from datetime import datetime
from uuid import UUID

from acme.om.exceptions import PreconditionFailed
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.relay.storage import RelayStorageInterface
from acme.om.relay.types.exec import (
    ExecControl,
    ExecItem,
    ExecPart,
    ExecState,
    WorkspaceBinding,
)
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class RelayStorageMemoryImpl(MemoryStorageBase, RelayStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._items: MemoryTable[ExecItem] = {}
        self._parts: MemoryTable[ExecPart] = {}
        self._controls: MemoryTable[ExecControl] = {}
        self._bindings: MemoryTable[WorkspaceBinding] = {}

    async def create_item(self, org_id: UUID, item: ExecItem) -> bool:
        async with self._lock:
            return self._insert(self._items, org_id, item)

    async def read_item(self, org_id: UUID, item_id: UUID) -> ExecItem | None:
        return self._get(self._items, org_id, item_id)

    async def read_items_by_key(
        self, org_id: UUID, session_id: UUID, key: UUID, limit: int
    ) -> list[ExecItem]:
        found = [
            item
            for item in self._rows(self._items, org_id)
            if item.session_id == session_id and item.key == key
        ]
        return sorted(found, key=lambda item: (item.created_at, item.id))[:limit]

    async def read_running(self, org_id: UUID, session_id: UUID, limit: int) -> list[ExecItem]:
        found = [
            item
            for item in self._rows(self._items, org_id)
            if item.session_id == session_id and item.state is ExecState.RUNNING
        ]
        return sorted(found, key=lambda item: (item.created_at, item.id))[:limit]

    async def write_item(
        self, org_id: UUID, item: ExecItem, expected_version: int
    ) -> ExecItem | None:
        async with self._lock:
            stored = self._get(self._items, org_id, item.id)
            if stored is None or stored.version != expected_version:
                return None
            self._put(self._items, org_id, item)
            return item

    async def read_expired(self, now: datetime, limit: int) -> list[tuple[UUID, ExecItem]]:
        return [
            (org_id, item)
            for org_id, item in self._rows_across_tenants(self._items)
            if item.state is ExecState.RUNNING
            and item.lease_expires_at is not None
            and item.lease_expires_at < now
        ][:limit]

    async def add_part(self, org_id: UUID, part: ExecPart) -> bool:
        async with self._lock:
            taken = any(
                held.row_id == part.row_id and held.seq == part.seq
                for held in self._rows(self._parts, org_id)
            )
            return not taken and self._insert(self._parts, org_id, part)

    async def read_parts(
        self, org_id: UUID, row_id: UUID, after_seq: int, limit: int
    ) -> list[ExecPart]:
        found = [
            part
            for part in self._rows(self._parts, org_id)
            if part.row_id == row_id and part.seq > after_seq
        ]
        return sorted(found, key=lambda part: part.seq)[:limit]

    async def add_control(
        self, org_id: UUID, control: ExecControl, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        async with self._lock:
            self._insert(self._controls, org_id, control, outbox_rows)

    async def read_controls(
        self, org_id: UUID, host_id: UUID, after: UUID | None, since: datetime, limit: int
    ) -> list[ExecControl]:
        return [
            control
            for control in self._rows(self._controls, org_id)
            if control.host_id == host_id
            and control.created_at >= since
            and (after is None or control.id > after)
        ][:limit]

    async def write_binding(
        self,
        org_id: UUID,
        binding: WorkspaceBinding,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        async with self._lock:
            stored = await self.read_binding(org_id, binding.session_id)
            stored_version = 0 if stored is None else stored.version
            if stored_version != expected_version or (
                stored is not None and stored.id != binding.id
            ):
                raise PreconditionFailed(
                    f"the workspace binding of session {binding.session_id} is no longer at "
                    f"version {expected_version}"
                )
            if stored is None and binding.id in self._bindings:
                raise PreconditionFailed(f"binding {binding.id} is another session's")
            self._put(self._bindings, org_id, binding, outbox_rows)

    async def read_binding(self, org_id: UUID, session_id: UUID) -> WorkspaceBinding | None:
        for binding in self._rows(self._bindings, org_id):
            if binding.session_id == session_id:
                return binding
        return None

    async def purge_session(self, org_id: UUID, session_id: UUID, limit: int) -> int:
        async with self._lock:
            purged = 0
            for table in (self._parts, self._controls, self._items, self._bindings):
                gone = [
                    entity_id
                    for entity_id, (row_org, entity) in table.items()
                    if row_org == org_id and getattr(entity, "session_id", None) == session_id
                ][:limit]
                for entity_id in gone:
                    del table[entity_id]
                purged += len(gone)
            return purged

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            purged = 0
            for table in (self._parts, self._controls, self._items, self._bindings):
                gone = [
                    entity_id for entity_id, (row_org, _) in table.items() if row_org == org_id
                ][:limit]
                for entity_id in gone:
                    del table[entity_id]
                purged += len(gone)
            return purged
