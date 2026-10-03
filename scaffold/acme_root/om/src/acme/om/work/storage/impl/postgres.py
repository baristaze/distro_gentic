from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Interval,
    and_,
    case,
    exists,
    func,
    literal,
    literal_column,
    or_,
    select,
    update,
)
from sqlalchemy.sql import Select

from acme.om.base import EMPTY_UUID, new_id, utcnow
from acme.om.exceptions import TenantMismatch, UniqueKeyTaken
from acme.om.storage.impl.pg_base import PLAN_WITH_VALUES, PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_values
from acme.om.work.storage import InsertOutcome, WorkStorageInterface
from acme.om.work.storage.tables.work_items import WorkItems
from acme.om.work.types.work_item import WorkItem, WorkStatus


class WorkStoragePostgresImpl(PgStorageBase, WorkStorageInterface):
    async def create_item(self, org_id: UUID, item: WorkItem) -> InsertOutcome:
        # The base reports a taken id as False (a retry) and names any other
        # unique key it hit; the only other ones here hold the idempotency key,
        # which a retrying caller and a relay that runs twice both meet, so it
        # is reported and the manager reads the row back by that key.
        try:
            if await self._insert(WorkItems, org_id, item):
                return InsertOutcome.INSERTED
        except UniqueKeyTaken:
            return InsertOutcome.KEY_EXISTS
        async with self._session_for(WorkItems, org_id=org_id) as session:
            row = await session.get(WorkItems, item.id)
        if row is None or row.org_id != org_id:
            # The id is taken and this tenant cannot read it: another tenant
            # holds it. The read says so when it returns the row, and the
            # policy says so by returning none.
            raise TenantMismatch(f"work item {item.id} is not in {org_id}")
        return InsertOutcome.ID_EXISTS

    async def write_item_if_held(
        self, org_id: UUID, claim_token: UUID, item: WorkItem
    ) -> WorkItem | None:
        values = to_values(item, WorkItems)
        values.pop("id", None)
        stmt = (
            update(WorkItems)
            .where(
                WorkItems.id == item.id,
                WorkItems.org_id == org_id,
                WorkItems.status == WorkStatus.CLAIMED.value,
                WorkItems.claim_token == claim_token,
            )
            .values(**values)
            .returning(WorkItems)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            written = to_model(row, WorkItem)
            await session.commit()
            return written

    async def write_item_if_failed(self, org_id: UUID, item: WorkItem) -> WorkItem | None:
        return await self._write_item_if(org_id, item, WorkStatus.FAILED)

    async def write_item_if_queued(self, org_id: UUID, item: WorkItem) -> WorkItem | None:
        return await self._write_item_if(org_id, item, WorkStatus.QUEUED)

    async def _write_item_if(
        self, org_id: UUID, item: WorkItem, status: WorkStatus
    ) -> WorkItem | None:
        """`item` over its row, in one statement, only while the row is at
        `status`."""
        values = to_values(item, WorkItems)
        values.pop("id", None)
        stmt = (
            update(WorkItems)
            .where(
                WorkItems.id == item.id,
                WorkItems.org_id == org_id,
                WorkItems.status == status.value,
            )
            .values(**values)
            .returning(WorkItems)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            written = to_model(row, WorkItem)
            await session.commit()
            return written

    async def claim_next(
        self, lane: str, kinds: Sequence[str], worker_id: str, lease: timedelta
    ) -> tuple[UUID, WorkItem] | None:
        now = utcnow()
        candidate = (
            select(WorkItems.id)
            .where(
                WorkItems.lane == lane,
                WorkItems.status == WorkStatus.QUEUED.value,
                WorkItems.kind.in_([str(kind) for kind in kinds]),
                WorkItems.available_at <= now,
            )
            # The item ready longest goes first, by the claim's index, so a
            # claim reads the first free row and not the whole ready backlog.
            .order_by(WorkItems.available_at, WorkItems.id)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        stmt = (
            update(WorkItems)
            .where(WorkItems.id == candidate)
            .values(
                status=WorkStatus.CLAIMED.value,
                claimed_by=worker_id,
                claim_token=new_id(),
                lease_expires_at=now + lease,
                attempts=WorkItems.attempts + 1,  # rules.attempts_after_claim, in SQL
                updated_at=now,
                updated_by=EMPTY_UUID,  # the claim is the platform's write
            )
            .returning(WorkItems)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            claimed = (row.org_id, to_model(row, WorkItem))
            await session.commit()
            return claimed

    async def count_claimed_ahead(self, org_id: UUID, item: WorkItem, now: datetime) -> int:
        stmt = select(func.count()).where(
            WorkItems.org_id == org_id,
            WorkItems.status == WorkStatus.CLAIMED.value,
            WorkItems.lease_expires_at > now,
            WorkItems.kind == item.kind,
            WorkItems.id != item.id,
            # Another lane, or before it in the claim order on its own.
            or_(
                WorkItems.lane != item.lane,
                WorkItems.available_at < item.available_at,
                and_(WorkItems.available_at == item.available_at, WorkItems.id < item.id),
            ),
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            return (await session.execute(stmt)).scalar_one()

    async def has_open_item(self, org_id: UUID, kind: str, target_id: UUID) -> bool:
        stmt = select(
            exists().where(
                WorkItems.org_id == org_id,
                WorkItems.status.in_((WorkStatus.QUEUED.value, WorkStatus.CLAIMED.value)),
                WorkItems.kind == kind,
                WorkItems.target_id == target_id,
            )
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            return bool((await session.execute(stmt)).scalar_one())

    async def requeue_stale(
        self, now: datetime, stagger: timedelta, limit: int
    ) -> list[tuple[UUID, WorkItem]]:
        stale_filter = (
            WorkItems.status == WorkStatus.CLAIMED.value,
            WorkItems.lease_expires_at < now,
        )
        # The batch is chosen and locked once, as `claim_pending` does it: an
        # item a worker is renewing or settling right now is skipped, and it
        # is the next pass's if its lease is still expired then.
        batch = (
            select(WorkItems.id, WorkItems.org_id)
            .where(*stale_filter)
            .order_by(WorkItems.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .cte("batch")
            .prefix_with("MATERIALIZED")
        )
        # The position of each item among its own tenant's in the batch.
        stale = select(
            batch.c.id,
            (func.row_number().over(partition_by=batch.c.org_id, order_by=batch.c.id) - 1).label(
                "position"
            ),
        ).subquery("stale")
        exhausted = WorkItems.attempts >= WorkItems.max_attempts  # rules.is_exhausted, in SQL
        staggered = (
            literal(now, DateTime(timezone=True)) + literal(stagger, Interval()) * stale.c.position
        )
        stmt = (
            update(WorkItems)
            .where(WorkItems.id == stale.c.id, *stale_filter)
            .values(
                status=case((exhausted, WorkStatus.FAILED.value), else_=WorkStatus.QUEUED.value),
                available_at=case((exhausted, WorkItems.available_at), else_=staggered),
                claimed_by=None,
                claim_token=None,
                lease_expires_at=None,
                last_error="lease expired",
                updated_at=now,
                updated_by=EMPTY_UUID,
            )
            .returning(WorkItems)
        )
        # Every tenant's expired leases, so the system scope, spelled here.
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            rows = (await session.execute(stmt)).scalars().all()
            changed = sorted(
                ((row.org_id, to_model(row, WorkItem)) for row in rows), key=lambda pair: pair[1].id
            )
            await session.commit()
            return changed

    async def purge_items(self, before: datetime, limit: int) -> int:
        stmt = delete_batch(
            WorkItems,
            WorkItems.status.in_([WorkStatus.DONE.value, WorkStatus.FAILED.value]),
            WorkItems.updated_at < before,
            limit=limit,
        )
        # Every tenant's settled items, so the system scope, spelled here.
        # Planned with its values, so the index serves an idle pass too.
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(PLAN_WITH_VALUES)
            purged = deleted(await session.execute(stmt))
            await session.commit()
            return purged

    async def oldest_ready_at(self, now: datetime) -> datetime | None:
        # The status is spelled as a literal, not bound: the partial index of
        # queued items is chosen only where the statement names its predicate,
        # and a prepared statement's generic plan sees a parameter instead.
        queued = literal_column(f"'{WorkStatus.QUEUED.value}'")
        stmt = select(func.min(WorkItems.available_at)).where(
            WorkItems.status == queued, WorkItems.available_at <= now
        )
        # Every tenant's queue, so the system scope, spelled here.
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            return (await session.execute(stmt)).scalar_one()

    async def count_failed_since(self, since: datetime) -> int:
        stmt = select(func.count()).where(
            WorkItems.status == WorkStatus.FAILED.value, WorkItems.updated_at > since
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            return (await session.execute(stmt)).scalar_one()

    async def count_ready_by_lane(self, prefix: str, now: datetime) -> dict[str, int]:
        # The status is a literal for the partial index of queued items, as
        # in `oldest_ready_at`.
        queued = literal_column(f"'{WorkStatus.QUEUED.value}'")
        stmt = (
            select(WorkItems.lane, func.count())
            .where(
                WorkItems.status == queued,
                WorkItems.available_at <= now,
                WorkItems.lane.startswith(prefix, autoescape=True),
            )
            .group_by(WorkItems.lane)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            return {lane: count for lane, count in (await session.execute(stmt)).all()}

    async def count_ready_ahead(self, item: WorkItem, now: datetime) -> int:
        queued = literal_column(f"'{WorkStatus.QUEUED.value}'")
        stmt = select(func.count()).where(
            WorkItems.status == queued,
            WorkItems.available_at <= now,
            WorkItems.lane == item.lane,
            WorkItems.id != item.id,
            or_(
                WorkItems.available_at < item.available_at,
                and_(WorkItems.available_at == item.available_at, WorkItems.id < item.id),
            ),
        )
        # A lane is shared by its tier's tenants, so the system scope.
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            return (await session.execute(stmt)).scalar_one()

    async def count_ready_on_lanes(
        self, org_id: UUID, lanes: Sequence[str], now: datetime
    ) -> dict[tuple[str, str], int]:
        if not lanes:
            return {}
        queued = literal_column(f"'{WorkStatus.QUEUED.value}'")
        stmt = (
            select(WorkItems.lane, WorkItems.kind, func.count())
            .where(
                WorkItems.org_id == org_id,
                WorkItems.status == queued,
                WorkItems.available_at <= now,
                WorkItems.lane.in_(list(lanes)),
            )
            .group_by(WorkItems.lane, WorkItems.kind)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).all()
        return {(lane, kind): count for lane, kind, count in rows}

    async def read_latest_for_target(
        self, org_id: UUID, kind: str, target_id: UUID
    ) -> WorkItem | None:
        stmt = (
            select(WorkItems)
            .where(
                WorkItems.org_id == org_id,
                WorkItems.kind == kind,
                WorkItems.target_id == target_id,
            )
            .order_by(WorkItems.created_at.desc(), WorkItems.id.desc())
            .limit(1)
        )
        return await self._one(stmt, org_id)

    async def read_item(self, org_id: UUID, item_id: UUID) -> WorkItem | None:
        stmt = select(WorkItems).where(WorkItems.org_id == org_id, WorkItems.id == item_id)
        return await self._one(stmt, org_id)

    async def read_item_by_key(self, org_id: UUID, idempotency_key: UUID) -> WorkItem | None:
        stmt = select(WorkItems).where(
            WorkItems.org_id == org_id, WorkItems.idempotency_key == idempotency_key
        )
        return await self._one(stmt, org_id)

    async def _one(self, stmt: Select[tuple[WorkItems]], org_id: UUID) -> WorkItem | None:
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, WorkItem)
