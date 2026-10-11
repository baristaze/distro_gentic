"""A machine of the platform's cloud pool, as the pool records it: one
virtual machine that runs the host program for one session. A warm machine
was started ahead of the session that claims it, and names none yet."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.base import Created, Identifiable, Platform
from acme.om.workspaces.types.snapshot import DIGEST, REFERENCE

MACHINE_NAME = r"^[a-z][a-z0-9-]{0,62}$"
"""How the machines' backend names a machine: short, since a backend may keep
a socket under the name, whose path its host bounds."""


class PoolMachine(Identifiable, Created):
    """One machine the cloud pool started, under its name in the machines'
    backend: the platform's own record, which names a tenant only once a
    session of the tenant claims the machine. While it is warm it names no
    tenant, no session, and no pool.
    Once a session claims it, it names the session, the session's pool of
    one, and the person its session's work is for (`bound_by`), who answers
    for its host. `key_digest` is the digest of the one-use key the machine
    was handed at its start; its host trades the key for a credential once,
    and the digest goes. `host_id` is the host that did. `restored_from` is
    the snapshot its disk started from, so a prepare asked again does not
    start it again. `started_at` is None while it starts, and `sealed_at`
    says when nothing in it could read its key from outside its disk any
    more."""

    name: str = Field(pattern=MACHINE_NAME)
    egress_open: bool
    tenant_id: UUID | None = None
    session_id: UUID | None = None
    pool_id: UUID | None = None
    bound_by: UUID | None = None
    host_id: UUID | None = None
    key_digest: str | None = None
    restored_from: UUID | None = None
    started_at: datetime | None = None
    sealed_at: datetime | None = None

    @property
    def warm(self) -> bool:
        """Started ahead, and claimed by no session yet."""
        return self.session_id is None


class MachineSnapshot(Platform):
    """A snapshot of a session's machine, kept by the machines' backend in its
    own store: the name it keeps it under, and the digest its disk is held
    to. Never the disk."""

    reference: str = Field(pattern=REFERENCE)
    digest: str = Field(pattern=DIGEST)
