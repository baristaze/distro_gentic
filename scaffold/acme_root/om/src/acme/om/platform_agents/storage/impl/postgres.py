from uuid import UUID

from sqlalchemy import select, update

from acme.om.exceptions import PreconditionFailed
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.platform_agents.storage import PlatformAgentsStorageInterface
from acme.om.platform_agents.storage.tables.validation_sessions import ValidationSessions
from acme.om.platform_agents.types.validation import ValidationSession
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values


class PlatformAgentsStoragePostgresImpl(PgStorageBase, PlatformAgentsStorageInterface):
    async def read_validation(self, org_id: UUID, session_id: UUID) -> ValidationSession | None:
        stmt = select(ValidationSessions).where(
            ValidationSessions.id == session_id, ValidationSessions.org_id == org_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, ValidationSession)

    async def create_validation(
        self, org_id: UUID, session: ValidationSession, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(ValidationSessions, org_id, session, outbox_rows)

    async def write_validation(
        self,
        org_id: UUID,
        session: ValidationSession,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        values = {k: v for k, v in to_values(session, ValidationSessions).items() if k != "id"}
        # The version is in the WHERE, so two writers from one snapshot
        # cannot both land.
        stmt = (
            update(ValidationSessions)
            .where(
                ValidationSessions.id == session.id,
                ValidationSessions.org_id == org_id,
                ValidationSessions.version == expected_version,
            )
            .values(**values)
            .returning(ValidationSessions.id)
        )
        async with self._session_for(ValidationSessions, org_id=org_id) as db:
            if (await db.execute(stmt)).scalar_one_or_none() is None:
                await db.rollback()
                raise PreconditionFailed(
                    f"validation session {session.id} is no longer at version {expected_version}"
                )
            for outbox_row in outbox_rows:
                db.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await db.commit()

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        stmt = delete_batch(ValidationSessions, ValidationSessions.org_id == org_id, limit=limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            purged = deleted(await session.execute(stmt))
            await session.commit()
            return purged
