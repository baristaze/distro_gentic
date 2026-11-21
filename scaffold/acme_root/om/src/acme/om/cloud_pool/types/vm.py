"""A VM of the platform's cloud pool, as the pool records it: one
VM that runs the host program for one session. A warm VM
was started ahead of the session that claims it, and names none yet."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.base import Created, Identifiable, OmBase

VM_NAME = r"^[a-z][a-z0-9-]{0,62}$"
"""How the VMs' backend names a VM: short, since a backend may keep
a socket under the name, whose path its host bounds."""


class PoolVm(Identifiable, Created):
    """One VM the cloud pool started, under its name in the VMs'
    backend: the platform's own record, which names a tenant only once a
    session of the tenant claims the VM. While it is warm it names no
    tenant, no session, and no pool.
    Once a session claims it, it names the session, the session's pool of
    one, and the person its session's work is for (`bound_by`), who answers
    for its host. `key_digest` is the digest of the one-use key the VM
    was handed at its start; its host trades the key for a credential once,
    and the digest goes. `host_id` is the host that did. `restored_from` is
    the snapshot whose directory it was claimed or started to take back,
    so a prepare asked again for it keeps the VM, and one asked for
    another replaces it. `started_at` is None until it first runs, and
    stays set
    once it has: a VM started again keeps its disk. `bound_at` is when
    it was last handed a key for its session: its start for the session,
    its claim, or its start again; its host enrolls within the boot bound
    and the wait after it. `sealed_at` says when nothing in it could read
    its key from outside its disk any more."""

    name: str = Field(pattern=VM_NAME)
    egress_open: bool
    tenant_id: UUID | None = None
    agent_session_id: UUID | None = None
    pool_id: UUID | None = None
    bound_by: UUID | None = None
    host_id: UUID | None = None
    key_digest: str | None = None
    restored_from: UUID | None = None
    started_at: datetime | None = None
    bound_at: datetime | None = None
    sealed_at: datetime | None = None

    @property
    def warm(self) -> bool:
        """Started ahead, and claimed by no session yet."""
        return self.agent_session_id is None

    @property
    def cold(self) -> bool:
        """Started for its session by the claim that made its row, so the
        session waits on its whole boot: it is bound as the row is
        written, at one instant. A warm VM is bound at its claim, after it
        started, and a VM started again at its new start."""
        return self.bound_at is not None and self.bound_at == self.created_at


class PoolClaim(OmBase):
    """What a claim got: the VM that serves its session, a warm one bound or
    its own row written. At the pool's maximum, a claim that takes no warm
    VM takes the place of an idle one, `displaced`: its row went under the
    claim's lock, and its VM goes before the claim's own starts."""

    vm: PoolVm
    displaced: PoolVm | None = None
