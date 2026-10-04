"""Wire types of a tenant's retention: its policy with each project's
narrowing, written whole on the version the caller read, and one session's
snapshot, which an erasure of its content answers with."""

from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field

from acme.om.privacy.types.session_privacy import StorageMode
from acme.om.retention.types.policy import MAX_PROJECTS, REGION
from acme.services.api.types.common import RequestBody, View


class RetentionPolicyBody(RequestBody):
    """How long what a session says is kept, and its shape, each counted
    from the session's creation, none for no end; where its content may
    rest, sealed when left out; whether nothing it says may be kept
    anywhere; and its region. A field left out narrows nothing. A content
    that outlives its shape, and zero retention that keeps content at
    rest, are refused."""

    content_lifetime: timedelta | None = Field(default=None, gt=timedelta(0))
    shape_lifetime: timedelta | None = Field(default=None, gt=timedelta(0))
    storage_mode: StorageMode | None = None
    zero_retention: bool = False
    region: str | None = Field(default=None, pattern=REGION)


class RetentionPolicyView(View):
    content_lifetime: timedelta | None
    shape_lifetime: timedelta | None
    storage_mode: StorageMode
    zero_retention: bool
    region: str | None


class ProjectRetentionBody(RequestBody):
    """What one project of the tenant narrows; it never widens the tenant's."""

    project_id: UUID
    policy: RetentionPolicyBody


class ProjectRetentionView(View):
    project_id: UUID
    policy: RetentionPolicyView


class RetentionRequest(RequestBody):
    """The tenant's whole policy, written over the version `If-Match` names,
    or, with no `If-Match`, as the tenant's first."""

    policy: RetentionPolicyBody = Field(default_factory=RetentionPolicyBody)
    projects: list[ProjectRetentionBody] = Field(
        default_factory=list[ProjectRetentionBody], max_length=MAX_PROJECTS
    )


class RetentionView(View):
    """The tenant's policy; version 0, the loosest, until its first write."""

    policy: RetentionPolicyView
    projects: list[ProjectRetentionView]
    version: int
    updated_at: datetime
    updated_by: UUID


class KeyDestructionView(View):
    """A session's key destroyed, as the tenant's key service reported it:
    the service, the key's name in it, when by its clock, and its receipt.
    No key material crosses."""

    service: str
    key_name: str = Field(validation_alias="key")
    destroyed_at: datetime
    receipt: str


class SessionRetentionView(View):
    """One session's snapshot: the policy it took, when its content and its
    shape expire, and when each did. `destruction` is the key service's
    report of the key it destroyed, none when the service holds the tenant's
    key alone and the platform's revocation is the destruction."""

    session_id: UUID
    project_id: UUID | None
    policy: RetentionPolicyView
    content_expires_at: datetime | None
    shape_expires_at: datetime | None
    content_expired_at: datetime | None
    destruction: KeyDestructionView | None
    shape_expired_at: datetime | None
