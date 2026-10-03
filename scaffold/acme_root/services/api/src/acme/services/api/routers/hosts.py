"""Host routes. A tenant's: its pools, the tokens that enroll hosts into
them, its hosts, and where its sessions run. A host's own: enroll once with
an enrollment token, then rotate its credential, beat, and claim with it.
Each function is one call into the hosts service."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.services.api.gateway.auth import Ctx, Rctx
from acme.services.api.gateway.hosts import EnrollmentBearer, Host
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.ratelimit import rate_limited
from acme.services.api.gateway.resolve import HostsService
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

router = APIRouter(tags=["hosts"])


@router.post("/host-pools", response_model=PoolView, status_code=201)
async def create_pool(
    ctx: Ctx, hosts: HostsService, body: CreatePoolRequest, idem: Idem
) -> Response:
    """A pool hosts enroll into. An owner's or an admin's."""
    return await idem.run(201, lambda attempt: hosts.create_pool(ctx, body, attempt.target_id))


@router.get("/host-pools", response_model=list[PoolView])
async def get_pools(ctx: Ctx, hosts: HostsService) -> list[PoolView]:
    return await hosts.get_pools(ctx)


@router.get("/host-pools/{pool_id}/hosts", response_model=list[HostView])
async def get_hosts(ctx: Ctx, hosts: HostsService, pool_id: UUID) -> list[HostView]:
    """The pool's hosts, each with whether it is online now."""
    return await hosts.get_hosts(ctx, pool_id)


@router.post("/host-pools/{pool_id}/enrollment-tokens", response_model=IssuedEnrollmentTokenView)
async def issue_enrollment_token(
    ctx: Ctx,
    hosts: HostsService,
    pool_id: UUID,
    body: IssueEnrollmentTokenRequest | None = None,
) -> IssuedEnrollmentTokenView:
    """A token that enrolls claimants of a kind into the pool, in the clear
    once: hosts, unless the body names a product's kind. A retry mints
    another, so it takes no Idempotency-Key; the one never read expires on
    its own."""
    kind = (body or IssueEnrollmentTokenRequest()).kind
    return await hosts.issue_enrollment_token(ctx, pool_id, kind)


@router.delete("/host-enrollment-tokens/{token_id}", response_model=EnrollmentTokenView)
async def revoke_enrollment_token(
    ctx: Ctx, hosts: HostsService, token_id: UUID
) -> EnrollmentTokenView:
    return await hosts.revoke_enrollment_token(ctx, token_id)


@router.delete("/hosts/{host_id}", response_model=HostView)
async def revoke_host(ctx: Ctx, hosts: HostsService, host_id: UUID) -> HostView:
    """Ends the host and its credentials at once; it is handed no more work."""
    return await hosts.revoke_host(ctx, host_id)


@router.get("/agent-sessions/{session_id}/placement", response_model=PlacementView)
async def placement_of(ctx: Ctx, hosts: HostsService, session_id: UUID) -> PlacementView:
    """Where the session runs; a pinned session with no host online waits."""
    return await hosts.placement_of(ctx, session_id)


@router.put("/agent-sessions/{session_id}/placement", response_model=PlacementView)
async def place_session(
    ctx: Ctx, hosts: HostsService, session_id: UUID, body: PlaceSessionRequest
) -> PlacementView:
    """A principal pins the session to a pool, or moves it to the cloud."""
    return await hosts.place_session(ctx, session_id, body)


@router.post(
    "/hosts/enrollments",
    response_model=IssuedHostCredentialView,
    dependencies=[rate_limited("login")],
)
async def enroll(
    rctx: Rctx, hosts: HostsService, token: EnrollmentBearer, body: EnrollRequest
) -> IssuedHostCredentialView:
    """A host enrolls once, with its tenant's enrollment token as its bearer,
    and gets a credential of its own. A retry enrolls another host, so it
    takes no Idempotency-Key."""
    return await hosts.enroll(rctx, token, body)


@router.post("/hosts/me/credentials", response_model=IssuedHostCredentialView)
async def rotate(rctx: Rctx, hosts: HostsService, host: Host) -> IssuedHostCredentialView:
    """The host's next credential; the one it called with ends after a short
    grace."""
    return await hosts.rotate(rctx, host)


@router.post("/hosts/me/heartbeats", response_model=HostView)
async def heartbeat(
    rctx: Rctx, hosts: HostsService, host: Host, body: HeartbeatRequest
) -> HostView:
    return await hosts.heartbeat(rctx, host, body)


@router.post("/hosts/me/claims", response_model=ClaimView)
async def claim(rctx: Rctx, hosts: HostsService, host: Host, body: ClaimRequest) -> ClaimView:
    """The next item pinned to this host or its pool, or none. The body
    states the version the host reads, and nothing it is handed."""
    return await hosts.claim(rctx, host, body)
