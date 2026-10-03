"""A claimant enrolled inside a tenant's wall, as the platform knows it: its
kind, the pool its enrollment named, and when it last called. A workspace
host is the platform's kind, and adds what it advertised and the version of
the work it reads. Its credential is a row of its own (`credential.py`);
the claimant itself holds nothing of the platform's."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from acme.om.base import Identifiable, Platform, Trackable

HostName = Annotated[str, StringConstraints(min_length=1, max_length=64)]

Capability = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,62}$")]
"""A thing the host found it can do at startup, such as `git`."""


class IsolationMode(StrEnum):
    """The isolation levels a host can run a workspace at, strongest first."""

    VM = "vm"  # a microVM or a VM per session
    CONTAINER = "container"  # a container per session
    DIRECTORY = "directory"  # a directory on the host, as a dedicated user


class Advertisement(Platform):
    """What a host says of itself, each value from a probe that passed at its
    startup: its operating system and shell, its capabilities, and the
    isolation modes it can provide. The platform stores what it is told and
    never adds to it."""

    os: str = Field(min_length=1, max_length=64)
    shell: str = Field(default="", max_length=64)
    capabilities: tuple[Capability, ...] = ()
    isolation_modes: tuple[IsolationMode, ...] = ()


class HostReport(Platform):
    """What a host states at every call that renews it: what it probed, and
    the version of `exec` work it reads."""

    advertisement: Advertisement
    exec_version: int = Field(ge=1)


class ClaimantEnrollment(Platform):
    """What a claimant of a product's kind presents beside its enrollment
    token, once: its name. Its kind and its pool are the token's, never the
    claimant's to name."""

    name: HostName


class Enrollment(HostReport):
    """What a host presents beside its enrollment token, once: its name, and
    its report. The pool is the token's, never the host's to name."""

    name: HostName


class EnrolledClaimant(Identifiable, Trackable):
    """One enrolled claimant, of the kind its enrollment token named: a host,
    or a product's own (`placement.kinds`). `created_by` is the person who
    issued the token it enrolled with: a claimant is no person and acts for
    nobody."""

    kind: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    pool_id: UUID
    name: HostName
    enrolled_with: UUID  # the enrollment token it presented, once
    last_seen_at: datetime
    revoked_at: datetime | None = None
    revoked_by: UUID | None = None


class Host(EnrolledClaimant):
    """One enrolled workspace host: the claimant of the host kind, with what
    it advertised and the version of `exec` work it reads."""

    advertisement: Advertisement
    exec_version: int = Field(ge=1)  # the version of `exec` work it reads


class ClaimantIdentity(Platform):
    """Who a claimant is, read off its credential at the gateway and nowhere
    else: its kind, its id, the tenant whose wall it sits in, its pool, and
    the credential it called with. Nothing in a claimant's call adds to
    it."""

    kind: str
    id: UUID
    org_id: UUID
    pool_id: UUID
    credential_id: UUID
    expires_at: datetime


class HostIdentity(ClaimantIdentity):
    """Who a host is: a claimant identity of the host kind, which the hosts
    manager builds only for a host's credential."""

    @property
    def host_id(self) -> UUID:
        return self.id


class HostStatus(Platform):
    """A host as its owner reads it: online while it called within the window
    and reads a version of `exec` work at or above the floor."""

    host: Host
    online: bool
