"""Routes of a product's claimant, the way a host's are. A tenant's: revoke
one. A claimant's own: enroll once with an enrollment token of its kind,
then rotate its credential, claim, and read, renew, and report the item
it holds, with that credential alone. Each function is one call into the
hosts service."""

from uuid import UUID

from fastapi import APIRouter

from acme.services.api.gateway.auth import Ctx, Rctx
from acme.services.api.gateway.hosts import Claimant, ClaimToken, EnrollmentBearer
from acme.services.api.gateway.ratelimit import rate_limited
from acme.services.api.gateway.resolve import HostsService
from acme.services.api.types.claimants import (
    ClaimantClaimView,
    ClaimantEnrollRequest,
    ClaimantReportRequest,
    ClaimantView,
    ClaimantWorkView,
    ExtendLeaseRequest,
    IssuedClaimantCredentialView,
)

router = APIRouter(tags=["claimants"])


@router.delete("/claimants/{claimant_id}", response_model=ClaimantView)
async def revoke_claimant(ctx: Ctx, hosts: HostsService, claimant_id: UUID) -> ClaimantView:
    """Ends the claimant and its credentials at once; it is handed no more
    work. An owner's or an admin's."""
    return await hosts.revoke_claimant(ctx, claimant_id)


@router.post(
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


@router.post("/claimants/me/credentials", response_model=IssuedClaimantCredentialView)
async def rotate_claimant(
    rctx: Rctx, hosts: HostsService, claimant: Claimant
) -> IssuedClaimantCredentialView:
    """The claimant's next credential; the one it called with ends after a
    short grace."""
    return await hosts.rotate_claimant(rctx, claimant)


@router.post("/claimants/me/claims", response_model=ClaimantClaimView)
async def claim(rctx: Rctx, hosts: HostsService, claimant: Claimant) -> ClaimantClaimView:
    """The next item of the claimant's kind on the lanes its identity names,
    or none. The call names nothing: what it is handed is its credential's
    to say."""
    return await hosts.claim_as(rctx, claimant)


@router.get("/claimants/me/items/{item_id}", response_model=ClaimantWorkView)
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


@router.post("/claimants/me/items/{item_id}/lease", response_model=ClaimantWorkView)
async def extend(
    rctx: Rctx, hosts: HostsService, claimant: Claimant, item_id: UUID, body: ExtendLeaseRequest
) -> ClaimantWorkView:
    """Renews the lease on the item the claimant holds."""
    return await hosts.extend_as(rctx, claimant, item_id, body)


@router.post("/claimants/me/items/{item_id}/report", response_model=ClaimantWorkView)
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
