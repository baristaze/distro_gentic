"""The two credentials of a host's life, each of a kind and a prefix of its
own, kept as digests. The enrollment token is a tenant's: it names one
pool and lets a host in. The host credential is the host's: short-lived,
rotated by the host before it ends, and the executor identity of every
call the host makes."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from acme.om.base import Created, Identifiable, Platform, Trackable


class EnrollmentToken(Identifiable, Trackable):
    """A token an owner or an admin issued for one pool. Every host that
    presents it before it expires or is revoked enrolls into that pool."""

    pool_id: UUID
    digest: str
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_by: UUID | None = None


class HostCredential(Identifiable, Created):
    """One credential of one host. It rotates once: the rotation mints the
    next, marks this one rotated, and moves its end to a short grace, so a
    call in flight with it still lands. A second rotation of it means two
    machines hold it, and ends the host."""

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


class IssuedHostCredential(Platform):
    """A host credential in the clear, once, with the identity it carries."""

    credential: str
    credential_id: UUID
    host_id: UUID
    pool_id: UUID
    expires_at: datetime
