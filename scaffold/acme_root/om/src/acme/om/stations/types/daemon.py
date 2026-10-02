"""A lab's daemon as the platform knows it: a credential of a kind and a
prefix of its own, kept as a digest, and the identity it resolves to. An
owner or an admin issues the first for one lab; the daemon rotates it
before it ends."""

from datetime import datetime
from uuid import UUID

from acme.om.base import Created, Identifiable, Platform


class DaemonCredential(Identifiable, Created):
    """One credential of one lab's daemon. `issued_by` is the person who
    issued the lab's first, who answers for what the daemon writes: a
    daemon is no person and acts for nobody."""

    lab_id: UUID
    issued_by: UUID
    digest: str
    expires_at: datetime


class IssuedDaemonCredential(Platform):
    """A daemon credential in the clear, once, with the lab it serves."""

    credential: str
    credential_id: UUID
    lab_id: UUID
    expires_at: datetime


class DaemonIdentity(Platform):
    """Who a daemon is, read off its credential at the gateway and nowhere
    else: the lab it serves, the tenant whose wall the lab sits in, the
    credential it called with, and the person who answers for it."""

    lab_id: UUID
    org_id: UUID
    credential_id: UUID
    issued_by: UUID
    expires_at: datetime
