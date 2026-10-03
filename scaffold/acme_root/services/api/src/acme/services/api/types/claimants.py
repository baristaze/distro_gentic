"""The wire types of a product's claimant: its enrollment, its credential,
the work it claims and answers for, and the claimant as its owner reads
it. A claimant's requests carry no kind, no pool, no tenant, and no lane:
those are its credential's."""

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import EMPTY_UUID
from acme.om.placement.types.claimant import ClaimantReport, ReportOutcome
from acme.om.work.types.work_item import WorkStatus
from acme.services.api.types.common import RequestBody, View


class ClaimantEnrollRequest(RequestBody):
    """A claimant's name, beside its enrollment token. The kind and the pool
    are the token's."""

    name: str = Field(min_length=1, max_length=64)


class IssuedClaimantCredentialView(View):
    """The claimant's own credential in the clear, once, under its kind's
    prefix, and the identity it carries. It lives an hour; the claimant
    rotates it before then."""

    secret_fields = frozenset({"token"})

    token: str | None
    credential_id: UUID
    kind: str
    claimant_id: UUID
    pool_id: UUID
    expires_at: datetime


class ClaimantView(View):
    """A claimant as its owner reads it."""

    id: UUID
    kind: str
    pool_id: UUID
    name: str
    last_seen_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class ClaimantWorkView(View):
    """One item a claimant holds, under a lease and the claim token its
    claim was handed, which its read, its renewal, and its report carry;
    none once its report handed it back. `payload` is the item's, as its
    kind fixes it. `org_id` is the tenant whose work it is, the claimant's
    own."""

    id: UUID
    org_id: UUID
    kind: str
    status: WorkStatus
    target_id: UUID
    payload: dict[str, Any]
    lease_expires_at: datetime | None
    attempts: int
    claim_token: UUID | None


class ClaimantClaimView(View):
    """What a claim answers: the item, or none when nothing is ready."""

    item: ClaimantWorkView | None


class ExtendLeaseRequest(RequestBody):
    """The claim token of the item whose lease the claimant renews."""

    claim_token: UUID


class ClaimantReportRequest(RequestBody):
    """A claimant's answer for an item it holds: done, or failed with why,
    under its claim token. It is held to the report's shape before anything
    reads it: a failure names its reason, within bounds, and a success
    names none."""

    claim_token: UUID
    outcome: ReportOutcome
    error: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def _held_to_the_reports_shape(self) -> Self:
        self.report(EMPTY_UUID)
        return self

    def report(self, item_id: UUID) -> ClaimantReport:
        return ClaimantReport(
            item_id=item_id, claim_token=self.claim_token, outcome=self.outcome, error=self.error
        )
