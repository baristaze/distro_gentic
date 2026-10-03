"""Storage of the hosts swimlane: a tenant's host pools, the tokens that
enroll claimants into them, the enrolled claimants with their credentials
(a host is one kind of claimant), and where each placed session runs. Every operation takes org_id first, except the two
lookups by a credential's digest, which find the tenant. A tenant's write
lands its outbox rows in the same commit."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.om.hosts.types.credential import EnrollmentToken, HostCredential, Rotation
from acme.om.hosts.types.host import EnrolledClaimant, Host, HostReport
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
    async def enroll(
        self,
        org_id: UUID,
        claimant: EnrolledClaimant | Host,
        credential: HostCredential,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        """The claimant and its first credential, in one commit; a host with
        what it advertised and the version it reads."""
        ...

    @abstractmethod
    async def read_host(self, org_id: UUID, host_id: UUID) -> Host | None:
        """The host; None for a claimant of another kind."""
        ...

    @abstractmethod
    async def read_claimant(self, org_id: UUID, claimant_id: UUID) -> EnrolledClaimant | None:
        """The claimant of any kind, a host's row among them, as its
        claimant's fields alone."""
        ...

    @abstractmethod
    async def read_hosts(self, org_id: UUID, pool_id: UUID, limit: int) -> list[Host]:
        """The pool's hosts in id order, revoked ones included, at most
        `limit`; a claimant of another kind is none of them."""
        ...

    @abstractmethod
    async def read_claimants(
        self, org_id: UUID, pool_id: UUID, limit: int
    ) -> list[EnrolledClaimant]:
        """The pool's claimants of every kind in id order, a host's row
        among them, as their claimant's fields alone, revoked ones
        included, at most `limit`."""
        ...

    @abstractmethod
    async def count_hosts(self, seen_since: datetime, floor: int) -> dict[tuple[bool, bool], int]:
        """Cross-tenant, for the platform's gauge of hosts, in the system
        scope: the hosts not revoked, of the host kind alone, by whether they called since
        `seen_since` and whether they read `exec` work at or above `floor`.
        A count, never a host."""
        ...

    @abstractmethod
    async def read_claimant_by_credential_digest(
        self, digest: str
    ) -> tuple[UUID, HostCredential, EnrolledClaimant] | None:
        """Cross-tenant: a claimant's call names no tenant, so its
        credential's digest finds the tenant with the credential and its
        claimant, of any kind."""
        ...

    @abstractmethod
    async def rotate_credential(
        self,
        org_id: UUID,
        retiring_id: UUID,
        at: datetime,
        retire_at: datetime,
        minted: HostCredential,
    ) -> Rotation:
        """A credential rotates once. In one commit: the retiring credential
        is marked rotated at `at` and ends at `retire_at` when that is
        sooner, every other live credential of the host ends at `at`, and
        `minted` lands. `REUSED`, with nothing landed, when the retiring
        credential rotated already; `MISSING` when the tenant holds no
        retiring credential of that claimant."""
        ...

    @abstractmethod
    async def mark_seen(
        self, org_id: UUID, claimant_id: UUID, at: datetime, report: HostReport | None = None
    ) -> bool:
        """The claimant's last call, and, for a host, what it stated then.
        False when the tenant holds no such claimant."""
        ...

    @abstractmethod
    async def revoke_claimant(
        self,
        org_id: UUID,
        claimant_id: UUID,
        at: datetime,
        by: UUID,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> EnrolledClaimant | None:
        """Ends the claimant of any kind and, with it, every credential it
        holds; one revoked already answers as stored and lands nothing. None
        when the tenant holds no such claimant."""
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
