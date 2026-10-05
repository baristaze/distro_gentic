from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from acme.om.base import EMPTY_UUID
from acme.om.exceptions import PreconditionFailed, TenantMismatch
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.retention.storage import RetentionStorageInterface
from acme.om.retention.storage.tables.retention_policies import RetentionPolicies
from acme.om.retention.storage.tables.session_retention import SessionRetentionRows
from acme.om.retention.types.policy import TenantRetention
from acme.om.retention.types.snapshot import SessionRetention
from acme.om.storage.impl.pg_base import PLAN_WITH_VALUES, PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values


class RetentionStoragePostgresImpl(PgStorageBase, RetentionStorageInterface):
    async def read_policy(self, org_id: UUID) -> TenantRetention | None:
        stmt = select(RetentionPolicies).where(RetentionPolicies.org_id == org_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, TenantRetention)

    async def create_policy(
        self, org_id: UUID, policy: TenantRetention, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(RetentionPolicies, org_id, policy, outbox_rows)

    async def write_policy(
        self,
        org_id: UUID,
        policy: TenantRetention,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        values = {k: v for k, v in to_values(policy, RetentionPolicies).items() if k != "id"}
        # The version is in the WHERE, so two writers from one read cannot
        # both land.
        stmt = (
            update(RetentionPolicies)
            .where(
                RetentionPolicies.id == policy.id,
                RetentionPolicies.org_id == org_id,
                RetentionPolicies.version == expected_version,
            )
            .values(**values)
            .returning(RetentionPolicies.id)
        )
        async with self._session_for(RetentionPolicies, org_id=org_id) as db:
            if (await db.execute(stmt)).scalar_one_or_none() is None:
                await db.rollback()
                raise PreconditionFailed(
                    f"retention policy {policy.id} is no longer at version {expected_version}"
                )
            for outbox_row in outbox_rows:
                db.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await db.commit()

    @staticmethod
    def _snapshot(org_id: UUID, session_id: UUID) -> Select[tuple[SessionRetentionRows]]:
        return select(SessionRetentionRows).where(
            SessionRetentionRows.org_id == org_id, SessionRetentionRows.session_id == session_id
        )

    async def create_snapshot(self, org_id: UUID, snapshot: SessionRetention) -> SessionRetention:
        """The insert meets the session's unique key when the tenant holds a
        snapshot of it, and lands nothing; another tenant's id is the
        primary key's, and refused."""
        insert = (
            pg_insert(SessionRetentionRows)
            .values(org_id=org_id, **to_values(snapshot, SessionRetentionRows))
            .on_conflict_do_nothing(
                index_elements=[SessionRetentionRows.org_id, SessionRetentionRows.session_id]
            )
            .returning(SessionRetentionRows.id)
        )
        async with self._session_for(SessionRetentionRows, org_id=org_id) as session:
            try:
                landed = (await session.execute(insert)).scalar_one_or_none() is not None
                if landed:
                    await session.commit()
                    return snapshot
                stored = (
                    await session.execute(self._snapshot(org_id, snapshot.session_id))
                ).scalar_one()
                await session.commit()
                return to_model(stored, SessionRetention)
            except IntegrityError as error:
                await session.rollback()
                raise TenantMismatch(
                    f"session retention {snapshot.id} is not in {org_id}"
                ) from error

    async def read_snapshot(self, org_id: UUID, session_id: UUID) -> SessionRetention | None:
        stmt = self._snapshot(org_id, session_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, SessionRetention)

    async def write_snapshot(
        self, org_id: UUID, snapshot: SessionRetention, expected_version: int
    ) -> bool:
        values = {
            k: v
            for k, v in to_values(snapshot, SessionRetentionRows).items()
            if k not in {"id", "session_id", "created_at"}
        }
        stmt = (
            update(SessionRetentionRows)
            .where(
                SessionRetentionRows.org_id == org_id,
                SessionRetentionRows.id == snapshot.id,
                SessionRetentionRows.session_id == snapshot.session_id,
                SessionRetentionRows.version == expected_version,
            )
            .values(**values)
            .returning(SessionRetentionRows.id)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            landed = (await session.execute(stmt)).scalar_one_or_none() is not None
            await session.commit()
            return landed

    async def read_behind(
        self, now: datetime, limit: int
    ) -> list[tuple[UUID, SessionRetention, TenantRetention]]:
        # A snapshot whose fold failed waits out its next attempt, so the
        # ones that cannot fold never fill every pass's batch.
        stmt = (
            select(SessionRetentionRows, RetentionPolicies)
            .join(RetentionPolicies, RetentionPolicies.org_id == SessionRetentionRows.org_id)
            .where(
                SessionRetentionRows.policy_version < RetentionPolicies.version,
                or_(
                    SessionRetentionRows.next_attempt_at.is_(None),
                    SessionRetentionRows.next_attempt_at <= now,
                ),
            )
            .limit(limit)
        )
        # Every tenant's snapshots behind their policy, so the system scope,
        # spelled here, planned with its values (ADR 0056).
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(PLAN_WITH_VALUES)
            return [
                (
                    snapshot.org_id,
                    to_model(snapshot, SessionRetention),
                    to_model(policy, TenantRetention),
                )
                for snapshot, policy in (await session.execute(stmt)).tuples()
            ]

    async def read_due(self, now: datetime, limit: int) -> list[tuple[UUID, SessionRetention]]:
        # No order: the batch is any `limit` of the rows the two partial
        # indexes hold past `now`, so a backlog is never sorted to take one.
        # A row a pass could not finish waits out its next attempt, so the
        # rows that cannot move yet never fill every pass's batch.
        stmt = (
            select(SessionRetentionRows)
            .where(
                or_(
                    SessionRetentionRows.next_attempt_at.is_(None),
                    SessionRetentionRows.next_attempt_at <= now,
                ),
                or_(
                    and_(
                        SessionRetentionRows.content_expires_at.is_not(None),
                        SessionRetentionRows.content_expired_at.is_(None),
                        SessionRetentionRows.content_expires_at <= now,
                    ),
                    and_(
                        SessionRetentionRows.shape_expires_at.is_not(None),
                        SessionRetentionRows.shape_expired_at.is_(None),
                        SessionRetentionRows.shape_expires_at <= now,
                    ),
                ),
            )
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(PLAN_WITH_VALUES)
            return [
                (row.org_id, to_model(row, SessionRetention))
                for row in (await session.execute(stmt)).scalars()
            ]

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """The snapshots first, so the policy goes last."""
        gone = 0
        for table in (SessionRetentionRows, RetentionPolicies):
            if gone >= limit:
                break
            stmt = delete_batch(table, table.org_id == org_id, limit=limit - gone)
            async with self._session_for(stmt, org_id=org_id) as session:
                gone += deleted(await session.execute(stmt))
                await session.commit()
        return gone
