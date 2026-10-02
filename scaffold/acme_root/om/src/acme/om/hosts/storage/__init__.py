"""Storage of the hosts swimlane: a tenant's host pools, the tokens that
enroll hosts into them, the hosts with their credentials, and where each
placed session runs. Every operation takes org_id first, except the two
lookups by a credential's digest, which find the tenant. A tenant's write
lands its outbox rows in the same commit."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.om.hosts.types.credential import EnrollmentToken, HostCredential
from acme.om.hosts.types.host import Host, HostReport
from acme.om.hosts.types.placement import SessionPlacement
from acme.om.hosts.types.pool import HostPool
from acme.om.outbox.types.row import OutboxRow


class HostsStorageInterface(ABC):
    @abstractmethod
    async def create_pool(
        self, org_id: UUID, pool: HostPool, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create; False, with nothing landed, when the id is written."""
        ...

    @abstractmethod
    async def read_pool(self, org_id: UUID, pool_id: UUID) -> HostPool | None: ...

    @abstractmethod
    async def read_pools(self, org_id: UUID, limit: int) -> list[HostPool]:
        """The tenant's pools in id order, at most `limit`."""
        ...

    @abstractmethod
    async def create_enrollment_token(
        self, org_id: UUID, token: EnrollmentToken, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create; False, with nothing landed, when the id is written."""
        ...

    @abstractmethod
    async def read_enrollment_token_by_digest(
        self, digest: str
    ) -> tuple[UUID, EnrollmentToken] | None:
        """Cross-tenant: the token a host presents names no tenant, so its
        digest finds the tenant with the token, revoked or expired included."""
        ...

    @abstractmethod
    async def revoke_enrollment_token(
        self,
        org_id: UUID,
        token_id: UUID,
        at: datetime,
        by: UUID,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> EnrollmentToken | None:
        """Ends the token at `at`; one revoked already answers as stored and
        lands nothing. None when the tenant holds no such token."""
        ...

    @abstractmethod
    async def enroll_host(
        self,
        org_id: UUID,
        host: Host,
        credential: HostCredential,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        """The host and its first credential, in one commit."""
        ...

    @abstractmethod
    async def read_host(self, org_id: UUID, host_id: UUID) -> Host | None: ...

    @abstractmethod
    async def read_hosts(self, org_id: UUID, pool_id: UUID, limit: int) -> list[Host]:
        """The pool's hosts in id order, revoked ones included, at most
        `limit`."""
        ...

    @abstractmethod
    async def read_host_by_credential_digest(
        self, digest: str
    ) -> tuple[UUID, HostCredential, Host] | None:
        """Cross-tenant: a host's call names no tenant, so its credential's
        digest finds the tenant with the credential and its host."""
        ...

    @abstractmethod
    async def rotate_credential(
        self,
        org_id: UUID,
        retiring_id: UUID,
        retire_at: datetime,
        minted: HostCredential,
    ) -> bool:
        """In one commit: the retiring credential ends at `retire_at`, when
        that is sooner than its end, and `minted` lands. False, with nothing
        landed, when the tenant holds no retiring credential of that host."""
        ...

    @abstractmethod
    async def mark_seen(
        self, org_id: UUID, host_id: UUID, at: datetime, report: HostReport
    ) -> bool:
        """The host's last call, and what it stated then. False when the
        tenant holds no such host."""
        ...

    @abstractmethod
    async def revoke_host(
        self,
        org_id: UUID,
        host_id: UUID,
        at: datetime,
        by: UUID,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> Host | None:
        """Ends the host and, with it, every credential it holds; one revoked
        already answers as stored and lands nothing. None when the tenant
        holds no such host."""
        ...

    @abstractmethod
    async def read_placement(self, org_id: UUID, session_id: UUID) -> SessionPlacement | None: ...

    @abstractmethod
    async def write_placement(
        self,
        org_id: UUID,
        placement: SessionPlacement,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        """A compare-and-set: 0 creates the session's row, any other version
        lands the placement over the one stored at it. `PreconditionFailed`,
        landing nothing, when the stored version is another."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of each table of a deleted tenant past its
        retention; returns how many went."""
        ...
