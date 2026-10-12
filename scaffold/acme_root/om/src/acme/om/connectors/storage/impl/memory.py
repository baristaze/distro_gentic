from uuid import UUID

from acme.om.connectors.storage import ConnectorStorageInterface
from acme.om.connectors.types.connector import Connector, SessionConnectors
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class ConnectorStorageMemoryImpl(MemoryStorageBase, ConnectorStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._connectors: MemoryTable[Connector] = {}
        self._pins: MemoryTable[SessionConnectors] = {}

    async def create_connector(
        self, org_id: UUID, connector: Connector, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            # One connector of a name in a tenant: the unique index the table holds.
            for held in self._rows(self._connectors, org_id):
                if held.name == connector.name and held.id != connector.id:
                    raise UniqueKeyTaken(f"the tenant holds a connector named {connector.name}")
            return self._insert(self._connectors, org_id, connector, outbox_rows)

    async def read_connector(self, org_id: UUID, connector_id: UUID) -> Connector | None:
        return self._get(self._connectors, org_id, connector_id)

    async def read_connectors(
        self, org_id: UUID, after: UUID | None, limit: int
    ) -> list[Connector]:
        rows = sorted(self._rows(self._connectors, org_id), key=lambda c: c.id)
        return [c for c in rows if after is None or c.id > after][:limit]

    async def update_connector(
        self, org_id: UUID, connector: Connector, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        async with self._lock:
            held = self._get(self._connectors, org_id, connector.id)
            if held is None or held.version + 1 != connector.version:
                raise PreconditionFailed(f"connector {connector.id} moved meanwhile")
            self._put(self._connectors, org_id, connector, outbox_rows)

    async def create_pin(self, org_id: UUID, pin: SessionConnectors) -> SessionConnectors:
        async with self._lock:
            held = self._get(self._pins, org_id, pin.id)
            if held is not None:
                return held
            self._put(self._pins, org_id, pin)
            return pin

    async def read_pin(self, org_id: UUID, session_id: UUID) -> SessionConnectors | None:
        return self._get(self._pins, org_id, session_id)

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            return _drop(self._pins, org_id, limit) + _drop(self._connectors, org_id, limit)


def _drop[E: Connector | SessionConnectors](table: MemoryTable[E], org_id: UUID, limit: int) -> int:
    ids = [row.id for org, row in table.values() if org == org_id][:limit]
    for row_id in ids:
        del table[row_id]
    return len(ids)
