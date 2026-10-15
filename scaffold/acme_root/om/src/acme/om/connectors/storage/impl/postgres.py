from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from acme.om.connectors.storage import ConnectorStorageInterface
from acme.om.connectors.storage.tables.agent_session_connectors import (
    AgentSessionConnectors as SessionConnectorRows,
)
from acme.om.connectors.storage.tables.connectors import Connectors
from acme.om.connectors.types.connector import AgentSessionConnectors, Connector
from acme.om.exceptions import PreconditionFailed, TenantMismatch
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values


class ConnectorStoragePostgresImpl(PgStorageBase, ConnectorStorageInterface):
    async def create_connector(
        self, org_id: UUID, connector: Connector, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(Connectors, org_id, connector, outbox_rows)

    async def read_connector(self, org_id: UUID, connector_id: UUID) -> Connector | None:
        stmt = select(Connectors).where(Connectors.org_id == org_id, Connectors.id == connector_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Connector)

    async def read_connectors(
        self, org_id: UUID, after: UUID | None, limit: int
    ) -> list[Connector]:
        stmt = select(Connectors).where(Connectors.org_id == org_id)
        if after is not None:
            stmt = stmt.where(Connectors.id > after)
        stmt = stmt.order_by(Connectors.id).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, Connector) for row in rows]

    async def update_connector(
        self, org_id: UUID, connector: Connector, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        values = {k: v for k, v in to_values(connector, Connectors).items() if k != "id"}
        # The version read is in the WHERE, so two writes from one read
        # cannot both land.
        stmt = (
            update(Connectors)
            .where(
                Connectors.org_id == org_id,
                Connectors.id == connector.id,
                Connectors.version == connector.version - 1,
            )
            .values(**values)
            .returning(Connectors.id)
        )
        async with self._session_for(stmt, org_id=org_id) as db:
            if (await db.execute(stmt)).scalar_one_or_none() is None:
                await db.rollback()
                raise PreconditionFailed(f"connector {connector.id} moved meanwhile")
            for outbox_row in outbox_rows:
                db.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await db.commit()

    async def create_pin(self, org_id: UUID, pin: AgentSessionConnectors) -> AgentSessionConnectors:
        stmt = (
            insert(SessionConnectorRows)
            .values({**to_values(pin, SessionConnectorRows), "org_id": org_id})
            .on_conflict_do_nothing(index_elements=[SessionConnectorRows.id])
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()
        held = await self.read_pin(org_id, pin.id)
        if held is None:
            raise TenantMismatch(f"session {pin.id} is not in {org_id}")
        return held

    async def read_pin(self, org_id: UUID, agent_session_id: UUID) -> AgentSessionConnectors | None:
        stmt = select(SessionConnectorRows).where(
            SessionConnectorRows.org_id == org_id, SessionConnectorRows.id == agent_session_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, AgentSessionConnectors)

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        gone = 0
        for table in (SessionConnectorRows, Connectors):
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                gone += deleted(await session.execute(stmt))
                await session.commit()
        return gone
