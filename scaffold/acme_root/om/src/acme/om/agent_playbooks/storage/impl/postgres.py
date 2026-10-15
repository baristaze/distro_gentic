from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from acme.om.agent_playbooks.storage import AgentPlaybookStorageInterface
from acme.om.agent_playbooks.storage.tables.agent_playbook_invocations import (
    AgentPlaybookInvocations,
)
from acme.om.agent_playbooks.storage.tables.agent_playbook_pins import AgentPlaybookPins
from acme.om.agent_playbooks.storage.tables.agent_playbooks import AgentPlaybooks
from acme.om.agent_playbooks.types.agent_playbook import (
    AgentPlaybook,
    AgentPlaybookInvocation,
    AgentPlaybookPin,
)
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values


class AgentPlaybookStoragePostgresImpl(PgStorageBase, AgentPlaybookStorageInterface):
    async def create_agent_playbook(
        self, org_id: UUID, agent_playbook: AgentPlaybook, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(AgentPlaybooks, org_id, agent_playbook, outbox_rows)

    async def read_agent_playbook(
        self, org_id: UUID, agent_playbook_id: UUID
    ) -> AgentPlaybook | None:
        stmt = select(AgentPlaybooks).where(
            AgentPlaybooks.org_id == org_id, AgentPlaybooks.id == agent_playbook_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, AgentPlaybook)

    async def read_latest(self, org_id: UUID, name: str) -> AgentPlaybook | None:
        stmt = (
            select(AgentPlaybooks)
            .where(AgentPlaybooks.org_id == org_id, AgentPlaybooks.name == name)
            .order_by(AgentPlaybooks.version.desc())
            .limit(1)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, AgentPlaybook)

    async def create_invocation(
        self, org_id: UUID, invocation: AgentPlaybookInvocation
    ) -> AgentPlaybookInvocation:
        stmt = (
            insert(AgentPlaybookInvocations)
            .values(**to_values(invocation, AgentPlaybookInvocations), org_id=org_id)
            .on_conflict_do_nothing(
                index_elements=[
                    AgentPlaybookInvocations.org_id,
                    AgentPlaybookInvocations.agent_session_id,
                    AgentPlaybookInvocations.agent_playbook_id,
                ]
            )
        )
        read = select(AgentPlaybookInvocations).where(
            AgentPlaybookInvocations.org_id == org_id,
            AgentPlaybookInvocations.agent_session_id == invocation.agent_session_id,
            AgentPlaybookInvocations.agent_playbook_id == invocation.agent_playbook_id,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()
        # The fence is the transaction's: the read that answers is a new one.
        async with self._session_for(read, org_id=org_id) as session:
            return to_model((await session.execute(read)).scalar_one(), AgentPlaybookInvocation)

    async def read_invocations(
        self, org_id: UUID, agent_session_id: UUID, limit: int
    ) -> list[AgentPlaybookInvocation]:
        stmt = (
            select(AgentPlaybookInvocations)
            .where(
                AgentPlaybookInvocations.org_id == org_id,
                AgentPlaybookInvocations.agent_session_id == agent_session_id,
            )
            .order_by(AgentPlaybookInvocations.created_at, AgentPlaybookInvocations.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, AgentPlaybookInvocation) for row in rows]

    async def put_pin(
        self, org_id: UUID, pin: AgentPlaybookPin, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        await self._upsert(AgentPlaybookPins, org_id, pin, outbox_rows)

    async def read_pin(
        self, org_id: UUID, kind: str, agent_project_id: UUID | None
    ) -> AgentPlaybookPin | None:
        stmt = select(AgentPlaybookPins).where(
            AgentPlaybookPins.org_id == org_id,
            AgentPlaybookPins.kind == kind,
            AgentPlaybookPins.agent_project_id.is_(None)
            if agent_project_id is None
            else AgentPlaybookPins.agent_project_id == agent_project_id,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, AgentPlaybookPin)

    async def read_pins(self, org_id: UUID, limit: int) -> list[AgentPlaybookPin]:
        stmt = (
            select(AgentPlaybookPins)
            .where(AgentPlaybookPins.org_id == org_id)
            .order_by(
                AgentPlaybookPins.kind,
                AgentPlaybookPins.agent_project_id.is_not(None),
                AgentPlaybookPins.agent_project_id,
            )
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, AgentPlaybookPin) for row in rows]

    async def delete_pin(
        self, org_id: UUID, pin_id: UUID, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        stmt = (
            delete(AgentPlaybookPins)
            .where(AgentPlaybookPins.org_id == org_id, AgentPlaybookPins.id == pin_id)
            .returning(AgentPlaybookPins.id)
        )
        async with self._session_for(AgentPlaybookPins, org_id=org_id) as session:
            if (await session.execute(stmt)).scalar_one_or_none() is None:
                await session.rollback()
                return False
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()
            return True

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        gone = 0
        for table in (AgentPlaybookPins, AgentPlaybookInvocations, AgentPlaybooks):
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                gone += deleted(await session.execute(stmt))
                await session.commit()
        return gone
