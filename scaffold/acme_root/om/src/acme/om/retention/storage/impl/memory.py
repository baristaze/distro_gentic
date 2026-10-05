from datetime import datetime
from uuid import UUID

from acme.om.exceptions import PreconditionFailed, TenantMismatch, UniqueKeyTaken
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.retention.storage import RetentionStorageInterface
from acme.om.retention.types.policy import TenantRetention
from acme.om.retention.types.snapshot import SessionRetention
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class RetentionStorageMemoryImpl(MemoryStorageBase, RetentionStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._policies: MemoryTable[TenantRetention] = {}
        self._snapshots: MemoryTable[SessionRetention] = {}

    async def read_policy(self, org_id: UUID) -> TenantRetention | None:
        found = self._rows(self._policies, org_id)
        return found[0] if found else None

    async def create_policy(
        self, org_id: UUID, policy: TenantRetention, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            if policy.id in self._policies:
                return False
            # One policy a tenant: the unique index the table holds.
            if self._rows(self._policies, org_id):
                raise UniqueKeyTaken(f"retention_policies {policy.id}: the tenant holds one")
            return self._insert(self._policies, org_id, policy, outbox_rows)

    async def write_policy(
        self,
        org_id: UUID,
        policy: TenantRetention,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        async with self._lock:
            found = self._get(self._policies, org_id, policy.id)
            if found is None or found.version != expected_version:
                raise PreconditionFailed(
                    f"retention policy {policy.id} is no longer at version {expected_version}"
                )
            self._put(self._policies, org_id, policy, outbox_rows)

    def _snapshot(self, org_id: UUID, session_id: UUID) -> SessionRetention | None:
        return next(
            (s for s in self._rows(self._snapshots, org_id) if s.session_id == session_id), None
        )

    async def create_snapshot(self, org_id: UUID, snapshot: SessionRetention) -> SessionRetention:
        async with self._lock:
            stored = self._snapshot(org_id, snapshot.session_id)
            if stored is not None:
                return stored
            if not self._insert(self._snapshots, org_id, snapshot):
                raise TenantMismatch(f"session retention {snapshot.id} is not in {org_id}")
            return snapshot

    async def read_snapshot(self, org_id: UUID, session_id: UUID) -> SessionRetention | None:
        return self._snapshot(org_id, session_id)

    async def write_snapshot(
        self, org_id: UUID, snapshot: SessionRetention, expected_version: int
    ) -> bool:
        async with self._lock:
            stored = self._snapshot(org_id, snapshot.session_id)
            if stored is None or stored.id != snapshot.id or stored.version != expected_version:
                return False
            self._put(self._snapshots, org_id, snapshot)
            return True

    async def read_behind(
        self, now: datetime, limit: int
    ) -> list[tuple[UUID, SessionRetention, TenantRetention]]:
        policies = {org_id: policy for org_id, policy in self._policies.values()}
        behind: list[tuple[UUID, SessionRetention, TenantRetention]] = []
        for org_id, snapshot in self._rows_across_tenants(self._snapshots):
            policy = policies.get(org_id)
            if (
                policy is not None
                and snapshot.policy_version < policy.version
                and (snapshot.next_attempt_at is None or snapshot.next_attempt_at <= now)
            ):
                behind.append((org_id, snapshot, policy))
        return behind[:limit]

    async def read_due(self, now: datetime, limit: int) -> list[tuple[UUID, SessionRetention]]:
        return [
            (org_id, snapshot)
            for org_id, snapshot in self._rows_across_tenants(self._snapshots)
            if (snapshot.next_attempt_at is None or snapshot.next_attempt_at <= now)
            and (
                (
                    snapshot.content_expires_at is not None
                    and snapshot.content_expires_at <= now
                    and snapshot.content_expired_at is None
                )
                or (
                    snapshot.shape_expires_at is not None
                    and snapshot.shape_expires_at <= now
                    and snapshot.shape_expired_at is None
                )
            )
        ][:limit]

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """The snapshots first, so the policy goes last."""
        async with self._lock:
            snapshots = [s.id for s in self._rows(self._snapshots, org_id)][:limit]
            for snapshot_id in snapshots:
                del self._snapshots[snapshot_id]
            policies = [p.id for p in self._rows(self._policies, org_id)][: limit - len(snapshots)]
            for policy_id in policies:
                del self._policies[policy_id]
            return len(snapshots) + len(policies)
