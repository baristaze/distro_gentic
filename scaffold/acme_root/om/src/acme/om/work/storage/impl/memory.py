from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from acme.om.base import EMPTY_UUID, new_id, utcnow
from acme.om.exceptions import TenantMismatch
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable
from acme.om.work.rules import attempts_after_claim, is_exhausted, stagger_delay
from acme.om.work.storage import InsertOutcome, WorkStorageInterface
from acme.om.work.types.work_item import WorkItem, WorkStatus


class WorkStorageMemoryImpl(MemoryStorageBase, WorkStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._items: MemoryTable[WorkItem] = {}

    async def create_item(self, org_id: UUID, item: WorkItem) -> InsertOutcome:
        async with self._lock:
            found = self._items.get(item.id)
            if found is not None:
                if found[0] != org_id:
                    raise TenantMismatch(f"work item {item.id} is not in {org_id}")
                return InsertOutcome.ID_EXISTS
            for existing in self._rows(self._items, org_id):
                if existing.idempotency_key == item.idempotency_key:
                    return InsertOutcome.KEY_EXISTS  # the key is taken in this tenant
            self._insert(self._items, org_id, item)
            return InsertOutcome.INSERTED

    async def write_item_if_held(
        self, org_id: UUID, claim_token: UUID, item: WorkItem
    ) -> WorkItem | None:
        async with self._lock:
            stored = self._get(self._items, org_id, item.id)
            if (
                stored is None
                or stored.status is not WorkStatus.CLAIMED
                or stored.claim_token != claim_token
            ):
                return None
            self._items[item.id] = (org_id, item)
            return item

    async def write_item_if_failed(self, org_id: UUID, item: WorkItem) -> WorkItem | None:
        return await self._write_item_if(org_id, item, WorkStatus.FAILED)

    async def write_item_if_queued(self, org_id: UUID, item: WorkItem) -> WorkItem | None:
        return await self._write_item_if(org_id, item, WorkStatus.QUEUED)

    async def _write_item_if(
        self, org_id: UUID, item: WorkItem, status: WorkStatus
    ) -> WorkItem | None:
        async with self._lock:
            stored = self._get(self._items, org_id, item.id)
            if stored is None or stored.status is not status:
                return None
            self._items[item.id] = (org_id, item)
            return item

    async def claim_next(
        self, lane: str, kinds: Sequence[str], worker_id: str, lease: timedelta
    ) -> tuple[UUID, WorkItem] | None:
        now = utcnow()
        async with self._lock:
            ready = [
                (org_id, item)
                for org_id, item in self._rows_across_tenants(self._items)
                if item.lane == lane
                and item.status is WorkStatus.QUEUED
                and item.kind in kinds
                and item.available_at <= now
            ]
            if not ready:
                return None
            # The item ready longest goes first, as the Postgres claim orders it.
            org_id, item = min(ready, key=lambda pair: (pair[1].available_at, pair[1].id))
            claimed = item.model_copy(
                update={
                    "status": WorkStatus.CLAIMED,
                    "claimed_by": worker_id,
                    "claim_token": new_id(),
                    "lease_expires_at": now + lease,
                    "attempts": attempts_after_claim(item.attempts),
                    "updated_at": now,
                    "updated_by": EMPTY_UUID,  # the claim is the platform's write
                }
            )
            self._items[item.id] = (org_id, claimed)
            return org_id, claimed

    async def count_claimed_ahead(self, org_id: UUID, item: WorkItem, now: datetime) -> int:
        return sum(
            1
            for other in self._rows(self._items, org_id)
            if other.kind == item.kind
            and other.id != item.id
            and other.status is WorkStatus.CLAIMED
            and other.lease_expires_at is not None
            and other.lease_expires_at > now
            and (
                other.lane != item.lane
                or (other.available_at, other.id) < (item.available_at, item.id)
            )
        )

    async def end_open_on_lane(
        self, org_id: UUID, lane: str, reason: str, now: datetime, limit: int
    ) -> list[WorkItem]:
        return await self._end_open(org_id, lambda item: item.lane == lane, reason, now, limit)

    async def end_open_for_target(
        self, org_id: UUID, kind: str, target_id: UUID, reason: str, now: datetime, limit: int
    ) -> list[WorkItem]:
        return await self._end_open(
            org_id,
            lambda item: item.kind == kind and item.target_id == target_id,
            reason,
            now,
            limit,
        )

    async def _end_open(
        self,
        org_id: UUID,
        matches: Callable[[WorkItem], bool],
        reason: str,
        now: datetime,
        limit: int,
    ) -> list[WorkItem]:
        async with self._lock:
            found = [
                item
                for item in self._rows(self._items, org_id)
                if item.status in (WorkStatus.QUEUED, WorkStatus.CLAIMED) and matches(item)
            ][:limit]
            ended: list[WorkItem] = []
            for item in found:
                done = item.model_copy(
                    update={
                        "status": WorkStatus.DONE,
                        "last_error": reason,
                        "claimed_by": None,
                        "claim_token": None,
                        "lease_expires_at": None,
                        "updated_at": now,
                        "updated_by": EMPTY_UUID,
                    }
                )
                self._items[item.id] = (org_id, done)
                ended.append(done)
            return ended

    async def has_open_item(self, org_id: UUID, kind: str, target_id: UUID) -> bool:
        return any(
            item.kind == kind
            and item.target_id == target_id
            and item.status in (WorkStatus.QUEUED, WorkStatus.CLAIMED)
            for item in self._rows(self._items, org_id)
        )

    async def requeue_stale(
        self, now: datetime, stagger: timedelta, limit: int
    ) -> list[tuple[UUID, WorkItem]]:
        changed: list[tuple[UUID, WorkItem]] = []
        positions: dict[UUID, int] = {}
        async with self._lock:
            stale = [
                (org_id, item)
                for org_id, item in self._rows_across_tenants(self._items)
                if item.status is WorkStatus.CLAIMED
                and item.lease_expires_at is not None
                and item.lease_expires_at < now
            ][:limit]
            for org_id, item in stale:
                # The position among the tenant's own items in the batch.
                position = positions.get(org_id, 0)
                positions[org_id] = position + 1
                if is_exhausted(item):
                    update = {"status": WorkStatus.FAILED}
                else:
                    update = {
                        "status": WorkStatus.QUEUED,
                        "available_at": now + stagger_delay(position, stagger),
                    }
                requeued = item.model_copy(
                    update={
                        **update,
                        "claimed_by": None,
                        "claim_token": None,
                        "lease_expires_at": None,
                        "last_error": "lease expired",
                        "updated_at": now,
                        "updated_by": EMPTY_UUID,
                    }
                )
                self._items[item.id] = (org_id, requeued)
                changed.append((org_id, requeued))
        return changed

    async def purge_items(self, before: datetime, limit: int) -> int:
        async with self._lock:
            gone = [
                item.id
                for _, item in self._rows_across_tenants(self._items)
                if item.status in (WorkStatus.DONE, WorkStatus.FAILED) and item.updated_at < before
            ][:limit]
            for item_id in gone:
                del self._items[item_id]
            return len(gone)

    async def oldest_ready_at(self, now: datetime) -> datetime | None:
        ready = [
            item.available_at
            for _, item in self._rows_across_tenants(self._items)
            if item.status is WorkStatus.QUEUED and item.available_at <= now
        ]
        return min(ready, default=None)

    async def count_failed_since(self, since: datetime) -> int:
        return sum(
            1
            for _, item in self._rows_across_tenants(self._items)
            if item.status is WorkStatus.FAILED and item.updated_at > since
        )

    async def count_ready_by_lane(self, prefix: str, now: datetime) -> dict[str, int]:
        depth: dict[str, int] = {}
        for _, item in self._rows_across_tenants(self._items):
            if self._ready(item, now) and item.lane.startswith(prefix):
                depth[item.lane] = depth.get(item.lane, 0) + 1
        return depth

    async def count_ready_ahead(self, item: WorkItem, now: datetime) -> int:
        return sum(
            1
            for _, other in self._rows_across_tenants(self._items)
            if self._ready(other, now)
            and other.lane == item.lane
            and other.id != item.id
            and (other.available_at, other.id) < (item.available_at, item.id)
        )

    async def count_ready_on_lanes(
        self, org_id: UUID, lanes: Sequence[str], now: datetime
    ) -> dict[tuple[str, str], int]:
        found: dict[tuple[str, str], int] = {}
        for item in self._rows(self._items, org_id):
            if self._ready(item, now) and item.lane in lanes:
                found[(item.lane, item.kind)] = found.get((item.lane, item.kind), 0) + 1
        return found

    async def read_latest_for_target(
        self, org_id: UUID, kind: str, target_id: UUID
    ) -> WorkItem | None:
        mine = [
            item
            for item in self._rows(self._items, org_id)
            if item.kind == kind and item.target_id == target_id
        ]
        return max(mine, key=lambda item: (item.created_at, item.id), default=None)

    @staticmethod
    def _ready(item: WorkItem, now: datetime) -> bool:
        return item.status is WorkStatus.QUEUED and item.available_at <= now

    async def read_item(self, org_id: UUID, item_id: UUID) -> WorkItem | None:
        return self._get(self._items, org_id, item_id)

    async def read_item_by_key(self, org_id: UUID, idempotency_key: UUID) -> WorkItem | None:
        return next(
            (
                item
                for item in self._rows(self._items, org_id)
                if item.idempotency_key == idempotency_key
            ),
            None,
        )
