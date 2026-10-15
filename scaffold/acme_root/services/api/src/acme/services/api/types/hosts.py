"""The wire types of hosts: a tenant's pools and the tokens that enroll
hosts into them, its hosts, where a session runs, and what a host sends
and is handed. A host's requests carry no pool, no tenant, and no lane:
those are its credential's."""

import base64
from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import EMPTY_UUID
from acme.om.exceptions import ValidationFailed
from acme.om.hosts.rules import HostState
from acme.om.hosts.types.host import Capability, IsolationMode
from acme.om.hosts.types.pool import Label, Region
from acme.om.placement.kinds import HOST
from acme.om.placement.types.claimant import ClaimantReport, ReportOutcome
from acme.om.retention.crossing import Crossing
from acme.om.watch.kinds import MAX_APPEND_BYTES, MAX_APPEND_ENTRIES
from acme.om.watch.types.live import MAX_ENTRY, Appended, SentEntry
from acme.om.work.types.work_item import WorkStatus
from acme.services.api.types.common import RequestBody, View
from acme.services.api.types.exec_relay import CrossingBody


class CreatePoolRequest(RequestBody):
    name: str = Field(min_length=1, max_length=64)
    region: Region
    labels: list[Label] = Field(default_factory=list[Label], max_length=32)


class PoolView(View):
    id: UUID
    name: str
    region: str
    labels: list[str]
    created_at: datetime
    created_by: UUID


class IssueEnrollmentTokenRequest(RequestBody):
    """The claimant kind the token enrolls: a host unless it names a kind a
    product registered."""

    kind: str = Field(default=HOST, pattern=r"^[a-z][a-z0-9_]{0,31}$")


class EnrollmentTokenView(View):
    id: UUID
    pool_id: UUID
    kind: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    created_by: UUID


class IssuedEnrollmentTokenView(View):
    """The token in the clear, once: it enrolls claimants of its kind into
    its pool until it expires or is revoked. It is minted on every call, so
    a retry mints another, and the one never read expires on its own."""

    secret_fields = frozenset({"token"})

    token: str | None
    enrollment: EnrollmentTokenView


class AdvertisementBody(RequestBody):
    """What a host probed at its startup, and nothing it did not."""

    os: str = Field(min_length=1, max_length=64)
    shell: str = Field(default="", max_length=64)
    capabilities: list[Capability] = Field(default_factory=list[Capability], max_length=64)
    isolation_modes: list[IsolationMode] = Field(default_factory=list[IsolationMode], max_length=3)


class AdvertisementView(View):
    os: str
    shell: str
    capabilities: list[str]
    isolation_modes: list[IsolationMode]


class EnrollRequest(RequestBody):
    """A host's name and its report, beside its enrollment token. The pool
    is the token's."""

    name: str = Field(min_length=1, max_length=64)
    advertisement: AdvertisementBody
    exec_version: int = Field(ge=1)


class HeartbeatRequest(RequestBody):
    advertisement: AdvertisementBody
    exec_version: int = Field(ge=1)


class ClaimRequest(RequestBody):
    """The version of `exec` work the host reads, and nothing else: what it
    is handed is its identity's to say."""

    exec_version: int = Field(ge=1)


class IssuedHostCredentialView(View):
    """The host's own credential in the clear, once, and the identity it
    carries. It lives an hour; the host rotates it before then."""

    secret_fields = frozenset({"token"})

    token: str | None
    credential_id: UUID
    host_id: UUID
    pool_id: UUID
    expires_at: datetime


class HostView(View):
    """A host as its owner reads it: online while it called within the
    window and reads a version of `exec` work the platform still hands."""

    id: UUID
    pool_id: UUID
    name: str
    advertisement: AdvertisementView
    exec_version: int
    last_seen_at: datetime
    online: bool
    revoked_at: datetime | None
    created_at: datetime


class ClaimedWorkView(View):
    """One item a host was handed, under a lease, as `exec` work of
    `wire_version`. `payload` is the item's, as its kind fixes it.
    `org_id` is the tenant whose work it is, the host's own."""

    id: UUID
    org_id: UUID
    kind: str
    target_id: UUID
    payload: dict[str, Any]
    lease_expires_at: datetime | None
    attempts: int
    wire_version: int


class ClaimView(View):
    """What a claim answers: the item, or none when nothing is ready."""

    item: ClaimedWorkView | None


class PlaceAgentSessionRequest(RequestBody):
    """One of the tenant's pools, or None for the cloud."""

    pool_id: UUID | None


class PlacementView(View):
    """Where a session runs. A pinned session with no host of its pool
    online is `waiting`; it never moves to the cloud by itself."""

    agent_session_id: UUID
    pool: PoolView | None
    hosts_online: int
    waiting: bool
    version: int


MAX_APPEND_CHARS = 4 * -(-MAX_APPEND_BYTES // 3)
"""The base64 of an append's most bytes: no entry's data runs longer."""


def _size(data: str) -> int:
    """The bytes base64 text spells, read off its length before it is
    decoded."""
    return len(data) * 3 // 4 - (len(data) - len(data.rstrip("=")))


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


class EntryBody(RequestBody):
    """One numbered entry of a stream: its bytes as they crossed the wall,
    in base64, and the hash its sender declared of them, a `stream_part`."""

    n: int = Field(ge=0, le=MAX_ENTRY)
    data: str = Field(max_length=MAX_APPEND_CHARS)
    crossing: CrossingBody


class ClaimantAppendRequest(RequestBody):
    """What a claimant appends to one stream of its kind for the item it
    holds, under its claim token: the stream it names, and its entries in
    their order, an entry numbered at or below the stream's last landing
    nothing. It is held to its bounds before anything reads it."""

    claim_token: UUID
    stream: UUID
    entries: list[EntryBody] = Field(min_length=1, max_length=MAX_APPEND_ENTRIES)

    @model_validator(mode="after")
    def _within_an_appends_bytes(self) -> Self:
        if sum(_size(entry.data) for entry in self.entries) > MAX_APPEND_BYTES:
            raise ValueError(f"an append carries at most {MAX_APPEND_BYTES} bytes")
        return self

    def appended(self) -> Appended:
        entries: list[SentEntry] = []
        for entry in self.entries:
            try:
                data = base64.b64decode(entry.data, validate=True)
            except ValueError:
                # Not base64, or text outside ASCII, which no base64 is.
                raise ValidationFailed("an entry's data is base64") from None
            crossing = Crossing(
                kind=entry.crossing.kind, sha256=entry.crossing.sha256, size=entry.crossing.size
            )
            entries.append(SentEntry(n=entry.n, data=data, crossing=crossing))
        return Appended(claim_token=self.claim_token, stream=self.stream, entries=tuple(entries))


class LaneLoadView(View):
    lane: str
    kind: str  # a work kind, the platform's or a product's
    ready: int


class HostStandingView(View):
    """Why a host takes no work: its state, what it advertised, the version
    of `exec` work it reads against the floor, when it last called, and what
    is ready on its pool's lane and its own."""

    host_id: UUID
    pool_id: UUID
    state: HostState
    revoked: bool
    advertisement: AdvertisementView
    exec_version: int
    exec_floor: int
    last_seen_at: datetime
    lanes: list[LaneLoadView]
