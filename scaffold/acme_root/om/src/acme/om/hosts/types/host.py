"""A workspace host inside a tenant's wall, as the platform knows it: the
pool its enrollment named, what it advertised, the version of the work it
reads, and when it last called. Its credential is a row of its own
(`credential.py`); the host itself holds nothing of the platform's."""

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


class Enrollment(HostReport):
    """What a host presents beside its enrollment token, once: its name, and
    its report. The pool is the token's, never the host's to name."""

    name: HostName


class Host(Identifiable, Trackable):
    """One enrolled host. `created_by` is the person who issued the token it
    enrolled with: the host is no person and acts for nobody."""

    pool_id: UUID
    name: HostName
    enrolled_with: UUID  # the enrollment token it presented, once
    advertisement: Advertisement
    exec_version: int = Field(ge=1)  # the version of `exec` work it reads
    last_seen_at: datetime
    revoked_at: datetime | None = None
    revoked_by: UUID | None = None


class HostIdentity(Platform):
    """Who a host is, read off its credential at the gateway and nowhere
    else: the host, the tenant whose wall it sits in, its pool, and the
    credential it called with. Nothing in a host's call adds to it."""

    host_id: UUID
    org_id: UUID
    pool_id: UUID
    credential_id: UUID
    expires_at: datetime


class HostStatus(Platform):
    """A host as its owner reads it: online while it called within the window
    and reads a version of `exec` work at or above the floor."""

    host: Host
    online: bool
