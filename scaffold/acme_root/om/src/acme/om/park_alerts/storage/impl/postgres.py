from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update

from acme.om.park_alerts.storage import ParkAlertStorageInterface
from acme.om.park_alerts.storage.tables.park_alerts import ParkAlerts
from acme.om.park_alerts.types.park_alert import ParkAlert
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model


class ParkAlertStoragePostgresImpl(PgStorageBase, ParkAlertStorageInterface):
    async def create_park_alert(self, org_id: UUID, park_alert: ParkAlert) -> bool:
        return await self._insert(ParkAlerts, org_id, park_alert)

    async def read_park_alert(self, org_id: UUID, park_alert_id: UUID) -> ParkAlert | None:
        stmt = select(ParkAlerts).where(ParkAlerts.org_id == org_id, ParkAlerts.id == park_alert_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, ParkAlert)

    async def read_park_alerts(self, org_id: UUID, recipient: UUID, limit: int) -> list[ParkAlert]:
        stmt = (
            select(ParkAlerts)
            .where(ParkAlerts.org_id == org_id, ParkAlerts.recipient == recipient)
            .order_by(ParkAlerts.created_at.desc(), ParkAlerts.id.desc())
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, ParkAlert) for row in rows]

    async def mark_read(
        self, org_id: UUID, recipient: UUID, park_alert_id: UUID, at: datetime
    ) -> ParkAlert | None:
        # The first mark holds: a row read already keeps its time.
        stmt = (
            update(ParkAlerts)
            .where(
                ParkAlerts.org_id == org_id,
                ParkAlerts.id == park_alert_id,
                ParkAlerts.recipient == recipient,
                ParkAlerts.read_at.is_(None),
            )
            .values(read_at=at)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()
        held = await self.read_park_alert(org_id, park_alert_id)
        return held if held is not None and held.recipient == recipient else None

    async def purge_agent_session(self, org_id: UUID, agent_session_id: UUID, limit: int) -> int:
        stmt = delete_batch(
            ParkAlerts,
            ParkAlerts.org_id == org_id,
            ParkAlerts.agent_session_id == agent_session_id,
            limit=limit,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            gone = deleted(await session.execute(stmt))
            await session.commit()
            return gone

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        stmt = delete_batch(ParkAlerts, ParkAlerts.org_id == org_id, limit=limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            gone = deleted(await session.execute(stmt))
            await session.commit()
            return gone
