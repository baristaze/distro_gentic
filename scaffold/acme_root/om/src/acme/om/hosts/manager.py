"""The hosts swimlane: a tenant's host pools and the tokens that enroll
claimants into them, a claimant's own credential and its claims, and where
each session runs. A workspace host is the platform's claimant kind; a
product's claimant enrolls and claims through the same path."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import RequestContext, TenantContext
from acme.om.hosts.types.credential import (
    EnrollmentToken,
    IssuedCredential,
    IssuedEnrollmentToken,
)
from acme.om.hosts.types.host import (
    ClaimantEnrollment,
    ClaimantIdentity,
    EnrolledClaimant,
    Enrollment,
    Host,
    HostIdentity,
    HostReport,
    HostStatus,
)
from acme.om.hosts.types.placement import PlacementState, SessionPlacement
from acme.om.hosts.types.pool import HostPool
from acme.om.placement.kinds import HOST
from acme.om.placement.types.claimant import ClaimantReport
from acme.om.work.types.work_item import WorkItem


class HostsManagerInterface(ABC):
    # A tenant's side: its pools, the tokens that let hosts in, and where its
    # sessions run.

    @abstractmethod
    async def create_pool(self, ctx: TenantContext, pool: HostPool) -> HostPool:
        """A pool under the caller's tenant, its provenance stamped from the
        context. A retry under the same id answers the row as stored.
        Requires the members permission, an owner's or an admin's: a pool is
        where machines join the tenant's work, as a member joins its people."""
        ...

    @abstractmethod
    async def get_pools(self, ctx: TenantContext) -> tuple[HostPool, ...]:
        """The tenant's pools, in the order they were made."""
        ...

    @abstractmethod
    async def get_hosts(self, ctx: TenantContext, pool_id: UUID) -> tuple[HostStatus, ...]:
        """The pool's live hosts, each with whether it is online now, the one
        seen last first. NotFound when the tenant holds no such pool."""
        ...

    @abstractmethod
    async def get_host(
        self, ctx: TenantContext, pool_id: UUID, host_id: UUID
    ) -> HostStatus | None:
        """The host, with whether it is online now, when it is one of the
        pool's, revoked or not: read by its id, so a pool of any size
        answers. None when the tenant holds no such host in that pool."""
        ...

    @abstractmethod
    async def get_claimants(
        self, ctx: TenantContext, pool_id: UUID
    ) -> tuple[EnrolledClaimant, ...]:
        """The pool's claimants of every kind, a host among them, revoked
        ones included, each with when it was last seen: what its owner
        revokes one by. NotFound when the tenant holds no such pool."""
        ...

    @abstractmethod
    async def issue_enrollment_token(
        self, ctx: TenantContext, pool_id: UUID, kind: str = HOST
    ) -> IssuedEnrollmentToken:
        """A token that enrolls claimants of `kind`, a registered claimant
        kind and a host unless named, into the pool until it expires or is revoked, in the clear
        once; only its digest is kept. Requires the members permission.
        NotFound when the tenant holds no such pool; ValidationFailed for a
        kind this process does not know."""
        ...

    @abstractmethod
    async def revoke_enrollment_token(self, ctx: TenantContext, token_id: UUID) -> EnrollmentToken:
        """Ends the token at once; the hosts it enrolled keep their own
        credentials. Requires the members permission."""
        ...

    @abstractmethod
    async def revoke_host(self, ctx: TenantContext, host_id: UUID) -> Host:
        """Ends the host and every credential it holds at once: its next call
        is refused, and it is handed no more work. Requires the members
        permission. NotFound for a claimant of another kind."""
        ...

    @abstractmethod
    async def revoke_claimant(self, ctx: TenantContext, claimant_id: UUID) -> EnrolledClaimant:
        """Ends the claimant of any kind and every credential it holds at
        once, as `revoke_host` ends a host. Requires the members
        permission."""
        ...

    @abstractmethod
    async def place_session(
        self, ctx: TenantContext, session_id: UUID, pool_id: UUID | None
    ) -> SessionPlacement:
        """A principal sets where the session runs: one of the tenant's pools,
        or the cloud with None. This is the one way a session's placement
        changes, and it places a tree's root: a sub-agent runs where its
        root runs, and placing one is `ValidationFailed`. Requires the write
        permission. NotFound when the tenant holds no such session or pool."""
        ...

    @abstractmethod
    async def placement_of(self, ctx: TenantContext, session_id: UUID) -> PlacementState:
        """Where the session runs and how many of its pool's hosts are online:
        a pinned session with none online waits, and reads so here. A
        sub-agent reads its root's. NotFound when the tenant holds no such
        session."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep's purge of a tenant deleted past its retention: its
        pools, tokens, hosts, credentials, and placements go; any other
        tenant costs nothing."""
        ...

    # A claimant's side: the transitions its calls make from the request
    # stage. A claimant is no person, so none of them builds a tenant stage
    # of its own.

    @abstractmethod
    async def enroll(
        self, rctx: RequestContext, token: str, enrollment: Enrollment
    ) -> IssuedCredential:
        """Platform-internal: a host enrolls with an enrollment token of the
        host kind, once, and gets a credential of its kind and prefix,
        short-lived, in the clear once. The tenant and the pool are the
        token's, never the host's. Refuses any credential but a live
        enrollment token of the host kind, and a host that reads `exec`
        work below the floor."""
        ...

    @abstractmethod
    async def enroll_claimant(
        self, rctx: RequestContext, token: str, enrollment: ClaimantEnrollment
    ) -> IssuedCredential:
        """Platform-internal: a claimant of a product's kind enrolls as a host
        does, and gets a credential under its kind's prefix. The kind, the
        tenant, and the pool are the token's, never the claimant's. Refuses
        any credential but a live enrollment token, one of the host kind,
        which enrolls with what it probed, and one of a kind this process
        does not know."""
        ...

    @abstractmethod
    async def authenticate(self, rctx: RequestContext, credential: str) -> HostIdentity:
        """Platform-internal: the host behind a host credential. Refuses any
        other kind of credential, an expired one, and a revoked host's. A
        rotated credential presented past its grace means two machines hold
        the host's identity: it is refused, and the host and every
        credential it holds are revoked."""
        ...

    @abstractmethod
    async def authenticate_claimant(
        self, rctx: RequestContext, credential: str
    ) -> ClaimantIdentity:
        """Platform-internal: the claimant of a product's kind behind its
        credential, held as `authenticate` holds a host's: its kind is its
        prefix's, and its tenant and pool its enrollment's. Refuses a host's
        credential, since a host claims with the version of `exec` work it
        reads, and a prefix no registered kind carries."""
        ...

    @abstractmethod
    async def rotate(self, rctx: RequestContext, claimant: ClaimantIdentity) -> IssuedCredential:
        """Platform-internal: the claimant's next credential, a host's or a
        product's, in the clear once. The one it called with ends after a
        short grace, so a call in flight with it lands, and every older one
        ends now. A credential rotates once: a second rotation of it means
        two machines hold it, so it is refused with CredentialExpired, and
        the claimant and every credential it holds are revoked."""
        ...

    @abstractmethod
    async def heartbeat(self, rctx: RequestContext, host: HostIdentity, report: HostReport) -> Host:
        """Platform-internal: the host is online, and states what it probed
        and the version it reads; the platform keeps what it is told and adds
        nothing to it."""
        ...

    @abstractmethod
    async def claim(
        self, rctx: RequestContext, host: HostIdentity, exec_version: int
    ) -> tuple[TenantContext, WorkItem] | None:
        """Platform-internal: the next item for the host, claimed by
        placement from the lanes of its identity alone: its own and its
        pool's, never one its call names. Refused, before any claim, when the
        version it reads is below the floor. Renews the host as a heartbeat
        does. None when nothing is ready."""
        ...

    @abstractmethod
    async def claim_as(
        self, rctx: RequestContext, claimant: ClaimantIdentity
    ) -> tuple[TenantContext, WorkItem] | None:
        """Platform-internal: the next item for a claimant of a product's
        kind, claimed by placement from the lanes of its identity alone and
        only the kinds registered for its kind (`placement.claim_for`). None
        when nothing is ready."""
        ...

    @abstractmethod
    async def held_as(
        self, rctx: RequestContext, claimant: ClaimantIdentity, item_id: UUID, claim_token: UUID
    ) -> WorkItem:
        """Platform-internal: the item the claimant holds under the claim
        token, in its own tenant (`placement.held_for`)."""
        ...

    @abstractmethod
    async def extend_as(
        self, rctx: RequestContext, claimant: ClaimantIdentity, item_id: UUID, claim_token: UUID
    ) -> WorkItem:
        """Platform-internal: renews the lease on an item the claimant holds,
        by the claim's lease (`placement.extend_for`)."""
        ...

    @abstractmethod
    async def report_as(
        self, rctx: RequestContext, claimant: ClaimantIdentity, report: ClaimantReport
    ) -> WorkItem:
        """Platform-internal: the claimant's answer for an item it holds
        (`placement.report_for`)."""
        ...
