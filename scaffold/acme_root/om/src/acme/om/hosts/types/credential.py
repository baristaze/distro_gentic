"""The two credentials of a host's life, each of a kind and a prefix of its
own, kept as digests. The enrollment token is a tenant's: it names one
pool and lets a host in. The host credential is the host's: short-lived,
rotated by the host before it ends, and the executor identity of every
call the host makes."""

from datetime import datetime
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
    """One credential of one host. A rotation mints the next and moves this
    one's end to a short grace, so a host whose answer was lost can rotate
    again with it."""

    host_id: UUID
    digest: str
    expires_at: datetime


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
