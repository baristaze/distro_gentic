"""The hosts swimlane: a tenant's host pools and the tokens that enroll
hosts into them, a host's own credential and its claims, and where each
session runs."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import RequestContext, TenantContext
from acme.om.hosts.types.credential import (
    EnrollmentToken,
    IssuedEnrollmentToken,
    IssuedHostCredential,
)
from acme.om.hosts.types.host import Enrollment, Host, HostIdentity, HostReport, HostStatus
from acme.om.hosts.types.placement import PlacementState, SessionPlacement
from acme.om.hosts.types.pool import HostPool
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
        """The pool's hosts, each with whether it is online now. NotFound
        when the tenant holds no such pool."""
        ...

    @abstractmethod
    async def issue_enrollment_token(
        self, ctx: TenantContext, pool_id: UUID
    ) -> IssuedEnrollmentToken:
        """A token that enrolls hosts into the pool until it expires or is
        revoked, in the clear once; only its digest is kept. Requires the
        members permission. NotFound when the tenant holds no such pool."""
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

    # A host's side: the transitions its calls make from the request stage.
    # A host is no person, so none of them builds a tenant stage of its own.

    @abstractmethod
    async def enroll(
        self, rctx: RequestContext, token: str, enrollment: Enrollment
    ) -> IssuedHostCredential:
        """Platform-internal: a host enrolls with an enrollment token, once,
        and gets a credential of its own kind and prefix, short-lived, in the
        clear once. The tenant and the pool are the token's, never the
        host's. Refuses any credential but a live enrollment token, and a
        host that reads `exec` work below the floor."""
        ...

    @abstractmethod
    async def authenticate(self, rctx: RequestContext, credential: str) -> HostIdentity:
        """Platform-internal: the host behind a host credential. Refuses any
        other kind of credential, an expired or rotated one, and a revoked
        host's."""
        ...

    @abstractmethod
    async def rotate(self, rctx: RequestContext, host: HostIdentity) -> IssuedHostCredential:
        """Platform-internal: the host's next credential, in the clear once.
        The one it called with ends after a short grace, so a host whose
        answer was lost rotates again with it."""
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
