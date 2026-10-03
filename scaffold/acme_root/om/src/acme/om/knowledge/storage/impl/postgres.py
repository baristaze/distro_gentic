from uuid import UUID

from sqlalchemy import ColumnElement, or_, select, update

from acme.om.exceptions import PreconditionFailed
from acme.om.knowledge.storage import KnowledgeStorageInterface
from acme.om.knowledge.storage.tables.knowledge_entries import KnowledgeEntries
from acme.om.knowledge.types.knowledge import Knowledge, KnowledgeStatus
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values


class KnowledgeStoragePostgresImpl(PgStorageBase, KnowledgeStorageInterface):
    async def create_entry(
        self, org_id: UUID, entry: Knowledge, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(KnowledgeEntries, org_id, entry, outbox_rows)

    async def read_entry(self, org_id: UUID, entry_id: UUID) -> Knowledge | None:
        stmt = select(KnowledgeEntries).where(
            KnowledgeEntries.org_id == org_id, KnowledgeEntries.id == entry_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Knowledge)

    async def read_entries(
        self, org_id: UUID, status: KnowledgeStatus, after: UUID | None, limit: int
    ) -> list[Knowledge]:
        stmt = select(KnowledgeEntries).where(
            KnowledgeEntries.org_id == org_id, KnowledgeEntries.status == status.value
        )
        if after is not None:
            stmt = stmt.where(KnowledgeEntries.id > after)
        stmt = stmt.order_by(KnowledgeEntries.id).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, Knowledge) for row in rows]

    async def read_reachable(
        self, org_id: UUID, project_id: UUID | None, after: UUID | None, limit: int
    ) -> list[Knowledge]:
        stmt = select(KnowledgeEntries).where(
            KnowledgeEntries.org_id == org_id,
            KnowledgeEntries.status == KnowledgeStatus.REVIEWED.value,
            _reached_by(project_id),
        )
        if after is not None:
            stmt = stmt.where(KnowledgeEntries.id > after)
        stmt = stmt.order_by(KnowledgeEntries.id).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, Knowledge) for row in rows]

    async def read_by_slug(
        self, org_id: UUID, project_id: UUID | None, slug: str
    ) -> Knowledge | None:
        stmt = (
            select(KnowledgeEntries)
            .where(
                KnowledgeEntries.org_id == org_id,
                KnowledgeEntries.slug == slug,
                KnowledgeEntries.status == KnowledgeStatus.REVIEWED.value,
                _reached_by(project_id),
            )
            .order_by(KnowledgeEntries.id)
            .limit(1)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Knowledge)

    async def update_entry(
        self, org_id: UUID, entry: Knowledge, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        values = {k: v for k, v in to_values(entry, KnowledgeEntries).items() if k != "id"}
        # The version read is in the WHERE, so two reviews from one read
        # cannot both land.
        stmt = (
            update(KnowledgeEntries)
            .where(
                KnowledgeEntries.org_id == org_id,
                KnowledgeEntries.id == entry.id,
                KnowledgeEntries.version == entry.version - 1,
            )
            .values(**values)
            .returning(KnowledgeEntries.id)
        )
        async with self._session_for(stmt, org_id=org_id) as db:
            if (await db.execute(stmt)).scalar_one_or_none() is None:
                await db.rollback()
                raise PreconditionFailed(f"knowledge {entry.id} moved meanwhile")
            for outbox_row in outbox_rows:
                db.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await db.commit()

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        stmt = delete_batch(KnowledgeEntries, KnowledgeEntries.org_id == org_id, limit=limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            gone = deleted(await session.execute(stmt))
            await session.commit()
            return gone


def _reached_by(project_id: UUID | None) -> ColumnElement[bool]:
    """The entries a session of `project_id` reaches: those of no project,
    and its project's own when it has one."""
    if project_id is None:
        return KnowledgeEntries.project_id.is_(None)
    return or_(KnowledgeEntries.project_id.is_(None), KnowledgeEntries.project_id == project_id)
