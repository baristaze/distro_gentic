"""Host routes. A tenant's: its pools, the tokens that enroll hosts into
them, its hosts, and where its sessions run. A host's own: enroll once with
an enrollment token, or, for a VM of the platform's cloud pool, with
the key the pool handed it, then rotate its credential, beat, and claim
with it.
Each function is one call into the hosts service.

Routes of a product's claimant, the way a host's are. A tenant's: list a
pool's, and revoke one. A claimant's own: enroll once with an enrollment token of its kind,
then rotate its credential, claim, and read, renew, and report the item
it holds, and append to its kind's stream for it and read the streams its
kind reads, with that credential alone. Each function is one call into the
hosts service, or the watch service for a stream.

On the operator plane, an operator who may read reads why a host takes no
work, as ids, counts, times, and states."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response

from acme.om.watch.kinds import STREAM_KIND
from acme.services.api.gateway.admin import OperatorCtx
from acme.services.api.gateway.admission import HOLDER_CALL
from acme.services.api.gateway.auth import Ctx, Rctx
from acme.services.api.gateway.hosts import Claimant, ClaimToken, EnrollmentBearer, Host
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.platform_resolve import AgentFleetService, HostsService, WatchService
from acme.services.api.gateway.ratelimit import rate_limited
from acme.services.api.types.hosts import (
    ClaimantAppendRequest,
    ClaimantClaimView,
    ClaimantEnrollRequest,
    ClaimantReportRequest,
    ClaimantView,
    ClaimantWorkView,
    ClaimRequest,
    ClaimView,
    CreatePoolRequest,
    EnrollmentTokenView,
    EnrollRequest,
    ExtendLeaseRequest,
    HeartbeatRequest,
    HostStandingView,
    HostView,
    IssuedClaimantCredentialView,
    IssuedEnrollmentTokenView,
    IssuedHostCredentialView,
    IssueEnrollmentTokenRequest,
    PlaceAgentSessionRequest,
    PlacementView,
    PoolView,
)
from acme.services.api.types.watch import ItemPageView

router = APIRouter(tags=["hosts"])


claimants = APIRouter(tags=["hosts"])


operator = APIRouter(prefix="/admin", tags=["hosts"])


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
    return await hosts.issue_enrollment_token(ctx, pool_id, body)


@router.delete("/host-enrollment-tokens/{token_id}", response_model=EnrollmentTokenView)
async def revoke_enrollment_token(
    ctx: Ctx, hosts: HostsService, token_id: UUID
) -> EnrollmentTokenView:
    return await hosts.revoke_enrollment_token(ctx, token_id)


@router.delete("/hosts/{host_id}", response_model=HostView)
async def revoke_host(ctx: Ctx, hosts: HostsService, host_id: UUID) -> HostView:
    """Ends the host and its credentials at once; it is handed no more work."""
    return await hosts.revoke_host(ctx, host_id)


@router.get("/agent-sessions/{agent_session_id}/placement", response_model=PlacementView)
async def placement_of(ctx: Ctx, hosts: HostsService, agent_session_id: UUID) -> PlacementView:
    """Where the session runs; a pinned session with no host online waits."""
    return await hosts.placement_of(ctx, agent_session_id)


@router.put("/agent-sessions/{agent_session_id}/placement", response_model=PlacementView)
async def place_session(
    ctx: Ctx, hosts: HostsService, agent_session_id: UUID, body: PlaceAgentSessionRequest
) -> PlacementView:
    """A principal pins the session to a pool, or moves it to the cloud."""
    return await hosts.place_session(ctx, agent_session_id, body)


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


@router.post(
    "/hosts/vm-enrollments",
    response_model=IssuedHostCredentialView,
    dependencies=[rate_limited("login")],
)
async def enroll_vm(
    rctx: Rctx, hosts: HostsService, key: EnrollmentBearer, body: EnrollRequest
) -> IssuedHostCredentialView:
    """The host of a VM the platform's cloud pool started trades the key
    the pool handed the VM, once, as its bearer, for a credential of
    its own. A 409 while the VM is warm and serves no session yet: it
    asks again. A retry after the trade is refused, so it takes no
    Idempotency-Key."""
    return await hosts.enroll_vm(rctx, key, body)


@router.post("/hosts/me/credentials", response_model=IssuedHostCredentialView)
async def rotate(rctx: Rctx, hosts: HostsService, host: Host) -> IssuedHostCredentialView:
    """The host's next credential; the one it called with ends after a short
    grace."""
    return await hosts.rotate(rctx, host)


@router.post("/hosts/me/heartbeats", response_model=HostView, dependencies=[HOLDER_CALL])
async def heartbeat(
    rctx: Rctx, hosts: HostsService, host: Host, body: HeartbeatRequest
) -> HostView:
    return await hosts.heartbeat(rctx, host, body)


@router.post("/hosts/me/claims", response_model=ClaimView)
async def claim(rctx: Rctx, hosts: HostsService, host: Host, body: ClaimRequest) -> ClaimView:
    """The next item pinned to this host or its pool, or none. The body
    states the version the host reads, and nothing it is handed."""
    return await hosts.claim(rctx, host, body)


@claimants.get("/host-pools/{pool_id}/claimants", response_model=list[ClaimantView])
async def get_claimants(ctx: Ctx, hosts: HostsService, pool_id: UUID) -> list[ClaimantView]:
    """The pool's claimants of every kind, a host among them, revoked ones
    included, each with its kind and when it was last seen: the id its
    owner revokes one by."""
    return await hosts.get_claimants(ctx, pool_id)


@claimants.delete("/claimants/{claimant_id}", response_model=ClaimantView)
async def revoke_claimant(ctx: Ctx, hosts: HostsService, claimant_id: UUID) -> ClaimantView:
    """Ends the claimant and its credentials at once; it is handed no more
    work. An owner's or an admin's."""
    return await hosts.revoke_claimant(ctx, claimant_id)


@claimants.post(
    "/claimants/enrollments",
    response_model=IssuedClaimantCredentialView,
    dependencies=[rate_limited("login")],
)
async def enroll_claimant(
    rctx: Rctx, hosts: HostsService, token: EnrollmentBearer, body: ClaimantEnrollRequest
) -> IssuedClaimantCredentialView:
    """A claimant enrolls once, with its tenant's enrollment token of its
    kind as its bearer, and gets a credential under its kind's prefix. A
    retry enrolls another claimant, so it takes no Idempotency-Key. A host
    enrolls at `/hosts/enrollments`, with what it probed."""
    return await hosts.enroll_claimant(rctx, token, body)


@claimants.post("/claimants/me/credentials", response_model=IssuedClaimantCredentialView)
async def rotate_claimant(
    rctx: Rctx, hosts: HostsService, claimant: Claimant
) -> IssuedClaimantCredentialView:
    """The claimant's next credential; the one it called with ends after a
    short grace."""
    return await hosts.rotate_claimant(rctx, claimant)


@claimants.post("/claimants/me/claims", response_model=ClaimantClaimView)
async def claim_claimant_work(
    rctx: Rctx, hosts: HostsService, claimant: Claimant
) -> ClaimantClaimView:
    """The next item of the claimant's kind on the lanes its identity names,
    or none. The call names nothing: what it is handed is its credential's
    to say."""
    return await hosts.claim_as(rctx, claimant)


@claimants.get("/claimants/me/items/{item_id}", response_model=ClaimantWorkView)
async def held(
    rctx: Rctx,
    hosts: HostsService,
    claimant: Claimant,
    item_id: UUID,
    claim_token: ClaimToken,
) -> ClaimantWorkView:
    """The item the claimant holds, under the claim token its claim was
    handed (the `Claim-Token` header). Any other is not found."""
    return await hosts.held_as(rctx, claimant, item_id, claim_token)


@claimants.post(
    "/claimants/me/items/{item_id}/lease",
    response_model=ClaimantWorkView,
    dependencies=[HOLDER_CALL],
)
async def extend(
    rctx: Rctx, hosts: HostsService, claimant: Claimant, item_id: UUID, body: ExtendLeaseRequest
) -> ClaimantWorkView:
    """Renews the lease on the item the claimant holds."""
    return await hosts.extend_as(rctx, claimant, item_id, body)


@claimants.post(
    "/claimants/me/items/{item_id}/report",
    response_model=ClaimantWorkView,
    dependencies=[HOLDER_CALL],
)
async def report(
    rctx: Rctx,
    hosts: HostsService,
    claimant: Claimant,
    item_id: UUID,
    body: ClaimantReportRequest,
) -> ClaimantWorkView:
    """The claimant's answer for the item it holds: done, or failed with
    why. A failure is retried until its attempts are spent."""
    return await hosts.report_as(rctx, claimant, item_id, body)


@claimants.post("/claimants/me/items/{item_id}/streams/{kind}", status_code=204)
async def append(
    rctx: Rctx,
    watch: WatchService,
    claimant: Claimant,
    item_id: UUID,
    kind: Annotated[str, Path(pattern=STREAM_KIND.pattern)],
    body: ClaimantAppendRequest,
) -> None:
    """Appends to a stream of a kind the claimant's own kind writes, for
    the item it holds under the body's claim token. Any other item, and
    any other kind, is not found; each call spends the credential's
    budget of writes."""
    await watch.append_as(rctx, claimant, item_id, kind, body)


@claimants.get("/claimants/me/items/{item_id}/streams/{kind}", response_model=ItemPageView)
async def read_streams(
    rctx: Rctx,
    watch: WatchService,
    claimant: Claimant,
    item_id: UUID,
    kind: Annotated[str, Path(pattern=STREAM_KIND.pattern)],
    claim_token: ClaimToken,
    after: Annotated[list[str] | None, Query()] = None,
) -> ItemPageView:
    """The item's open streams of a kind the claimant's own kind reads, for
    the item it holds under the claim token its claim was handed (the
    `Claim-Token` header) with a live lease, each after the last entry read
    (`after=<stream>:<last>`, once a stream). Any other item, any other
    kind, and a lapsed lease are not found; each call spends the
    credential's budget of reads."""
    return await watch.read_as(rctx, claimant, item_id, kind, claim_token, after or [])


@operator.get("/orgs/{org_id}/hosts/{host_id}/standing", response_model=HostStandingView)
async def host_standing(
    admin: OperatorCtx, service: AgentFleetService, org_id: UUID, host_id: UUID
) -> HostStandingView:
    """Why the host takes no work: what it advertised and the version it
    reads, against the floor and what is ready on its lanes."""
    return await service.get_host_standing(admin, org_id, host_id)
