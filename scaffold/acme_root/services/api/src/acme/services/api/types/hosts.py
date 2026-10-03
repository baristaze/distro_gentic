"""The wire types of hosts: a tenant's pools and the tokens that enroll
hosts into them, its hosts, where a session runs, and what a host sends
and is handed. A host's requests carry no pool, no tenant, and no lane:
those are its credential's."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from acme.om.hosts.types.host import Capability, IsolationMode
from acme.om.hosts.types.pool import Label, Region
from acme.services.api.types.common import RequestBody, View


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


class EnrollmentTokenView(View):
    id: UUID
    pool_id: UUID
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    created_by: UUID


class IssuedEnrollmentTokenView(View):
    """The token in the clear, once: it enrolls hosts into its pool until
    it expires or is revoked. It is minted on every call, so a retry mints
    another, and the one never read expires on its own."""

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


class PlaceSessionRequest(RequestBody):
    """One of the tenant's pools, or None for the cloud."""

    pool_id: UUID | None


class PlacementView(View):
    """Where a session runs. A pinned session with no host of its pool
    online is `waiting`; it never moves to the cloud by itself."""

    session_id: UUID
    pool: PoolView | None
    hosts_online: int
    waiting: bool
    version: int
