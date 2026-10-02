"""A session's retention: the policy it took when it was created, and what
the sweep has done to it since.

The snapshot is taken once, before the session's row is written, so no
session is without one. Its lifetimes count from then. The sweep folds a
tightening of the tenant's policy into it and never a loosening, so its
policy and its expiries only ever move earlier. When its content expires,
the sweep destroys the session's key and keeps the key service's report
here; when its shape does, the sweep marks the session deleted."""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import Created, Identifiable
from acme.om.retention.keys import KeyDestruction
from acme.om.retention.types.policy import RetentionPolicy


class SessionRetention(Identifiable, Created):
    """One per session of a tenant. `created_at` is when it was taken, as
    the session was created, and every lifetime counts from it.
    `policy_version` is the version of the tenant's policy last folded
    into it, 0 for a tenant with none. `at_rest` says whether the session's
    content rests sealed, as it does unless the session began memory-only.
    Every write after the first is a compare-and-set on `version`."""

    session_id: UUID
    project_id: UUID | None = None
    policy: RetentionPolicy
    policy_version: int = Field(default=0, ge=0)
    at_rest: bool
    content_expires_at: datetime | None = None
    shape_expires_at: datetime | None = None
    # When the sweep took up its content's expiry, and the key service's
    # report of the key it destroyed then; no report when the service
    # holds the tenant's key alone, and the engine's revocation is the
    # destruction.
    content_expired_at: datetime | None = None
    destruction: KeyDestruction | None = None
    # When the sweep marked the session deleted, its shape past its life.
    shape_expired_at: datetime | None = None
    # When the sweep takes the session up again, after a pass that could not
    # finish what was due: until then it is out of every pass's read.
    next_attempt_at: datetime | None = None
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _a_report_follows_a_destruction(self) -> Self:
        if self.destruction is not None and self.content_expired_at is None:
            raise ValueError("a key service's report is kept with the destruction it reports")
        return self
