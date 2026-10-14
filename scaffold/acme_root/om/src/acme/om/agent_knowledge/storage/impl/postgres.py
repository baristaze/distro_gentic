from uuid import UUID

from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from acme.om.agent_knowledge.storage import AgentKnowledgeStorageInterface
from acme.om.agent_knowledge.storage.tables.agent_knowledge_entries import AgentKnowledgeEntries
from acme.om.agent_knowledge.storage.tables.agent_knowledge_recalls import AgentKnowledgeRecalls
from acme.om.agent_knowledge.types.agent_knowledge import (
    AgentKnowledge,
    AgentKnowledgeRecall,
    AgentKnowledgeStatus,
)
from acme.om.exceptions import PreconditionFailed
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values


class AgentKnowledgeStoragePostgresImpl(PgStorageBase, AgentKnowledgeStorageInterface):
    async def create_entry(
        self, org_id: UUID, entry: AgentKnowledge, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(AgentKnowledgeEntries, org_id, entry, outbox_rows)

    async def read_entry(self, org_id: UUID, entry_id: UUID) -> AgentKnowledge | None:
        stmt = select(AgentKnowledgeEntries).where(
            AgentKnowledgeEntries.org_id == org_id, AgentKnowledgeEntries.id == entry_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, AgentKnowledge)

    async def read_entries(
        self, org_id: UUID, status: AgentKnowledgeStatus, after: UUID | None, limit: int
    ) -> list[AgentKnowledge]:
        stmt = select(AgentKnowledgeEntries).where(
            AgentKnowledgeEntries.org_id == org_id, AgentKnowledgeEntries.status == status.value
        )
        if after is not None:
            stmt = stmt.where(AgentKnowledgeEntries.id > after)
        stmt = stmt.order_by(AgentKnowledgeEntries.id).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, AgentKnowledge) for row in rows]

    async def read_reachable(
        self, org_id: UUID, project_id: UUID | None, after: UUID | None, limit: int
    ) -> list[AgentKnowledge]:
        stmt = select(AgentKnowledgeEntries).where(
            AgentKnowledgeEntries.org_id == org_id,
            AgentKnowledgeEntries.status == AgentKnowledgeStatus.REVIEWED.value,
            _reached_by(project_id),
        )
        if after is not None:
            stmt = stmt.where(AgentKnowledgeEntries.id > after)
        stmt = stmt.order_by(AgentKnowledgeEntries.id).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, AgentKnowledge) for row in rows]

    async def read_by_slug(
        self, org_id: UUID, project_id: UUID | None, slug: str
    ) -> AgentKnowledge | None:
        stmt = (
            select(AgentKnowledgeEntries)
            .where(
                AgentKnowledgeEntries.org_id == org_id,
                AgentKnowledgeEntries.slug == slug,
                AgentKnowledgeEntries.status == AgentKnowledgeStatus.REVIEWED.value,
                _reached_by(project_id),
            )
            .order_by(AgentKnowledgeEntries.id)
            .limit(1)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, AgentKnowledge)

    async def update_entry(
        self, org_id: UUID, entry: AgentKnowledge, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        values = {k: v for k, v in to_values(entry, AgentKnowledgeEntries).items() if k != "id"}
        # The version read is in the WHERE, so two reviews from one read
        # cannot both land.
        stmt = (
            update(AgentKnowledgeEntries)
            .where(
                AgentKnowledgeEntries.org_id == org_id,
                AgentKnowledgeEntries.id == entry.id,
                AgentKnowledgeEntries.version == entry.version - 1,
            )
            .values(**values)
            .returning(AgentKnowledgeEntries.id)
        )
        async with self._session_for(stmt, org_id=org_id) as db:
            if (await db.execute(stmt)).scalar_one_or_none() is None:
                await db.rollback()
                raise PreconditionFailed(f"agent knowledge {entry.id} moved meanwhile")
            for outbox_row in outbox_rows:
                db.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await db.commit()

    async def create_recalls(self, org_id: UUID, recalls: tuple[AgentKnowledgeRecall, ...]) -> None:
        if not recalls:
            return
        stmt = (
            insert(AgentKnowledgeRecalls)
            .values([{**to_values(r, AgentKnowledgeRecalls), "org_id": org_id} for r in recalls])
            .on_conflict_do_nothing(
                index_elements=[
                    AgentKnowledgeRecalls.org_id,
                    AgentKnowledgeRecalls.session_id,
                    AgentKnowledgeRecalls.entry_id,
                ]
            )
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()

    async def read_recalls(
        self, org_id: UUID, session_id: UUID, limit: int
    ) -> list[AgentKnowledgeRecall]:
        stmt = (
            select(AgentKnowledgeRecalls)
            .where(
                AgentKnowledgeRecalls.org_id == org_id,
                AgentKnowledgeRecalls.session_id == session_id,
            )
            .order_by(AgentKnowledgeRecalls.created_at, AgentKnowledgeRecalls.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, AgentKnowledgeRecall) for row in rows]

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        gone = 0
        for table in (AgentKnowledgeRecalls, AgentKnowledgeEntries):
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                gone += deleted(await session.execute(stmt))
                await session.commit()
        return gone


def _reached_by(project_id: UUID | None) -> ColumnElement[bool]:
    """The entries a session of `project_id` reaches: those of no project,
    and its project's own when it has one."""
    if project_id is None:
        return AgentKnowledgeEntries.project_id.is_(None)
    return or_(
        AgentKnowledgeEntries.project_id.is_(None), AgentKnowledgeEntries.project_id == project_id
    )
