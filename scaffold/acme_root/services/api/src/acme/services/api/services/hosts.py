"""The hosts service: what the wire can do with a tenant's pools, its
hosts and its other claimants, and where its sessions run, and what a
host's or a product's claimant's own calls do, in views."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import RequestContext, TenantContext
from acme.om.hosts.types.host import ClaimantIdentity, HostIdentity
from acme.services.api.types.claimants import (
    ClaimantClaimView,
    ClaimantEnrollRequest,
    ClaimantReportRequest,
    ClaimantView,
    ClaimantWorkView,
    ExtendLeaseRequest,
    IssuedClaimantCredentialView,
)
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
    IssueEnrollmentTokenRequest,
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
        self, ctx: TenantContext, pool_id: UUID, body: IssueEnrollmentTokenRequest | None
    ) -> IssuedEnrollmentTokenView:
        """A token of the kind the body names, a host's with no body."""
        ...

    @abstractmethod
    async def revoke_enrollment_token(
        self, ctx: TenantContext, token_id: UUID
    ) -> EnrollmentTokenView: ...

    @abstractmethod
    async def revoke_host(self, ctx: TenantContext, host_id: UUID) -> HostView: ...

    @abstractmethod
    async def revoke_claimant(self, ctx: TenantContext, claimant_id: UUID) -> ClaimantView: ...

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

    # A product's claimant's calls.

    @abstractmethod
    async def enroll_claimant(
        self, rctx: RequestContext, token: str, body: ClaimantEnrollRequest
    ) -> IssuedClaimantCredentialView: ...

    @abstractmethod
    async def rotate_claimant(
        self, rctx: RequestContext, claimant: ClaimantIdentity
    ) -> IssuedClaimantCredentialView: ...

    @abstractmethod
    async def claim_as(
        self, rctx: RequestContext, claimant: ClaimantIdentity
    ) -> ClaimantClaimView: ...

    @abstractmethod
    async def held_as(
        self, rctx: RequestContext, claimant: ClaimantIdentity, item_id: UUID, claim_token: UUID
    ) -> ClaimantWorkView: ...

    @abstractmethod
    async def extend_as(
        self,
        rctx: RequestContext,
        claimant: ClaimantIdentity,
        item_id: UUID,
        body: ExtendLeaseRequest,
    ) -> ClaimantWorkView: ...

    @abstractmethod
    async def report_as(
        self,
        rctx: RequestContext,
        claimant: ClaimantIdentity,
        item_id: UUID,
        body: ClaimantReportRequest,
    ) -> ClaimantWorkView: ...
