"""A lab's daemon as the platform knows it: a credential of a kind and a
prefix of its own, kept as a digest, and the identity it resolves to. An
owner or an admin issues the first for one lab; the daemon rotates it
before it ends."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from acme.om.base import Created, Identifiable, Platform


class DaemonCredential(Identifiable, Created):
    """One credential of one lab's daemon. `issued_by` is the person who
    issued the lab's first, who answers for what the daemon writes: a
    daemon is no person and acts for nobody. It rotates once: the rotation
    marks it rotated and moves its end to a short grace, so a call in
    flight with it still lands. A revocation marks it revoked, which no
    clock reads past."""

    lab_id: UUID
    issued_by: UUID
    digest: str
    expires_at: datetime
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None


class Rotation(StrEnum):
    """What became of a rotation, in storage."""

    ROTATED = "rotated"  # the next credential landed, and this one is marked
    REUSED = "reused"  # this one rotated already; nothing landed
    REVOKED = "revoked"  # this one is revoked; nothing landed
    MISSING = "missing"  # no such credential of the lab; nothing landed


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
