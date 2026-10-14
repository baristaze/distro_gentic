from datetime import datetime
from uuid import UUID

from acme.om.park_alerts.storage import ParkAlertStorageInterface
from acme.om.park_alerts.types.park_alert import ParkAlert
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class ParkAlertStorageMemoryImpl(MemoryStorageBase, ParkAlertStorageInterface):
    def __init__(self) -> None:
        super().__init__(None)
        self._park_alerts: MemoryTable[ParkAlert] = {}

    async def create_park_alert(self, org_id: UUID, park_alert: ParkAlert) -> bool:
        async with self._lock:
            return self._insert(self._park_alerts, org_id, park_alert, ())

    async def read_park_alert(self, org_id: UUID, park_alert_id: UUID) -> ParkAlert | None:
        return self._get(self._park_alerts, org_id, park_alert_id)

    async def read_park_alerts(self, org_id: UUID, recipient: UUID, limit: int) -> list[ParkAlert]:
        rows = [n for n in self._rows(self._park_alerts, org_id) if n.recipient == recipient]
        return sorted(rows, key=lambda n: (n.created_at, n.id), reverse=True)[:limit]

    async def mark_read(
        self, org_id: UUID, recipient: UUID, park_alert_id: UUID, at: datetime
    ) -> ParkAlert | None:
        async with self._lock:
            held = self._get(self._park_alerts, org_id, park_alert_id)
            if held is None or held.recipient != recipient:
                return None
            if held.read_at is None:
                held = held.model_copy(update={"read_at": at})
                self._park_alerts[held.id] = (org_id, held)
            return held

    async def purge_session(self, org_id: UUID, session_id: UUID, limit: int) -> int:
        async with self._lock:
            ids = [
                row.id
                for org, row in self._park_alerts.values()
                if org == org_id and row.session_id == session_id
            ][:limit]
            for row_id in ids:
                del self._park_alerts[row_id]
            return len(ids)

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            ids = [row.id for org, row in self._park_alerts.values() if org == org_id][:limit]
            for row_id in ids:
                del self._park_alerts[row_id]
            return len(ids)
