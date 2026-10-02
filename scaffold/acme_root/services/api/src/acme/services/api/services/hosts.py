"""The hosts service: what the wire can do with a tenant's pools, its
hosts, and where its sessions run, and what a host's own calls do, in
views."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import RequestContext, TenantContext
from acme.om.hosts.types.host import HostIdentity
from acme.services.api.types.hosts import (
    ClaimRequest,
    ClaimView,
    CreatePoolRequest,
    EnrollmentTokenView,
    EnrollRequest,
    HeartbeatRequest,
    HostView,
    IssuedEnrollmentTokenView,
    IssuedHostCredentialView,
    PlacementView,
    PlaceSessionRequest,
    PoolView,
)


class HostsServiceInterface(ABC):
    # A tenant's calls.

    @abstractmethod
    async def create_pool(
        self, ctx: TenantContext, body: CreatePoolRequest, pool_id: UUID
    ) -> PoolView:
        """A pool under `pool_id`, the id the idempotency record minted."""
        ...

    @abstractmethod
    async def get_pools(self, ctx: TenantContext) -> list[PoolView]: ...

    @abstractmethod
    async def get_hosts(self, ctx: TenantContext, pool_id: UUID) -> list[HostView]: ...

    @abstractmethod
    async def issue_enrollment_token(
        self, ctx: TenantContext, pool_id: UUID
    ) -> IssuedEnrollmentTokenView: ...

    @abstractmethod
    async def revoke_enrollment_token(
        self, ctx: TenantContext, token_id: UUID
    ) -> EnrollmentTokenView: ...

    @abstractmethod
    async def revoke_host(self, ctx: TenantContext, host_id: UUID) -> HostView: ...

    @abstractmethod
    async def place_session(
        self, ctx: TenantContext, session_id: UUID, body: PlaceSessionRequest
    ) -> PlacementView: ...

    @abstractmethod
    async def placement_of(self, ctx: TenantContext, session_id: UUID) -> PlacementView: ...

    # A host's calls.

    @abstractmethod
    async def enroll(
        self, rctx: RequestContext, token: str, body: EnrollRequest
    ) -> IssuedHostCredentialView: ...

    @abstractmethod
    async def rotate(
        self, rctx: RequestContext, host: HostIdentity
    ) -> IssuedHostCredentialView: ...

    @abstractmethod
    async def heartbeat(
        self, rctx: RequestContext, host: HostIdentity, body: HeartbeatRequest
    ) -> HostView: ...

    @abstractmethod
    async def claim(
        self, rctx: RequestContext, host: HostIdentity, body: ClaimRequest
    ) -> ClaimView: ...
