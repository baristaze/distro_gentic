"""Storage of the retention swimlane: each tenant's policy, and each
session's snapshot of it. Every operation takes org_id first, but the
sweep's two reads, which cross tenants in the system scope and name each
row's tenant.

A policy is written once and then by a compare-and-set on its version. A
snapshot is written once, as its session is created, and then by a
compare-and-set on its own version."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.om.outbox.types.row import OutboxRow
from acme.om.retention.types.policy import TenantRetention
from acme.om.retention.types.snapshot import SessionRetention


class RetentionStorageInterface(ABC):
    @abstractmethod
    async def read_policy(self, org_id: UUID) -> TenantRetention | None: ...

    @abstractmethod
    async def create_policy(
        self, org_id: UUID, policy: TenantRetention, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The tenant's first policy, with the rows that announce it. False,
        with nothing landed, when its id is written already;
        `UniqueKeyTaken` when the tenant holds another."""
        ...

    @abstractmethod
    async def write_policy(
        self,
        org_id: UUID,
        policy: TenantRetention,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        """The compare-and-set: `policy` replaces the stored one while the
        stored one is still at `expected_version`, with the rows that
        announce it. `PreconditionFailed`, with nothing written, otherwise."""
        ...

    @abstractmethod
    async def create_snapshot(self, org_id: UUID, snapshot: SessionRetention) -> SessionRetention:
        """The session's snapshot, written once: `snapshot` lands when the
        session has none, and the stored one is answered either way."""
        ...

    @abstractmethod
    async def read_snapshot(self, org_id: UUID, session_id: UUID) -> SessionRetention | None: ...

    @abstractmethod
    async def write_snapshot(
        self, org_id: UUID, snapshot: SessionRetention, expected_version: int
    ) -> bool:
        """The compare-and-set: `snapshot` replaces the stored one while the
        stored one is still at `expected_version`. False, with nothing
        written, otherwise."""
        ...

    @abstractmethod
    async def read_behind(self, limit: int) -> list[tuple[UUID, SessionRetention, TenantRetention]]:
        """Cross-tenant: the sweep's read, in the system scope, of at most
        `limit` snapshots that have not yet folded their tenant's current
        policy, each named with its tenant and that policy."""
        ...

    @abstractmethod
    async def read_due(self, now: datetime, limit: int) -> list[tuple[UUID, SessionRetention]]:
        """Cross-tenant: the sweep's read, in the system scope, of at most
        `limit` snapshots whose content or whose shape has expired by `now`
        and is not yet taken up, each named with its tenant. A snapshot whose
        next attempt is after `now` is left out."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of a deleted tenant past its retention, the
        snapshots before the policy; returns how many."""
        ...
