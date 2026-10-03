"""The two credentials of a claimant's life, each of a kind and a prefix of
its own, kept as digests. The enrollment token is a tenant's: it names one
pool and one claimant kind, and lets a claimant of that kind in. The
claimant's credential is its own, under its kind's prefix: short-lived,
rotated by the claimant before it ends, and the executor identity of every
call it makes. A host is one claimant kind; a product registers others."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from acme.om.base import Created, Identifiable, Platform, Trackable


class EnrollmentToken(Identifiable, Trackable):
    """A token an owner or an admin issued for one pool and one claimant
    kind. Every claimant that presents it before it expires or is revoked
    enrolls into that pool, as that kind: the kind, the pool, and the tenant
    are the token's, never the claimant's to name."""

    pool_id: UUID
    kind: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    digest: str
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_by: UUID | None = None


class HostCredential(Identifiable, Created):
    """One credential of one enrolled claimant, a host or a product's;
    `host_id` is the claimant's id. It rotates once: the rotation mints the
    next, marks this one rotated, and moves its end to a short grace, so a
    call in flight with it still lands. A second rotation of it means two
    machines hold it, and ends the claimant."""

    host_id: UUID
    digest: str
    expires_at: datetime
    rotated_at: datetime | None = None


class Rotation(StrEnum):
    """What became of a rotation, in storage."""

    ROTATED = "rotated"  # the next credential landed, and this one is marked
    REUSED = "reused"  # this one rotated already; nothing landed
    MISSING = "missing"  # no such credential of the host; nothing landed


class IssuedEnrollmentToken(Platform):
    """An enrollment token in the clear, once."""

    token: str
    enrollment: EnrollmentToken


class IssuedCredential(Platform):
    """A claimant's credential in the clear, once, with the identity it
    carries: its kind, its id, and its pool."""

    credential: str
    credential_id: UUID
    kind: str
    claimant_id: UUID
    pool_id: UUID
    expires_at: datetime
