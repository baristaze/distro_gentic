"""Where a snapshot a session keeps lives: the platform's bucket, for a
workspace of the platform's cloud, the store of the host inside its
tenant's wall that took it, for a workspace a host holds, or the store of
the VMs' backend, for a VM of the cloud pool. The platform
records the reference and the hash, never the bytes; the history's
`snapshotted` step names the snapshot by its id and its hash."""

from typing import ClassVar
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.agent_steps.types.header import SNAPSHOT_HASH
from acme.om.base import Identifiable, OmBase, Trackable

DIGEST = r"^sha256:[0-9a-f]{64}$"
"""The digest a host declares of the bytes it keeps: their SHA-256."""

REFERENCE = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$"
"""How a store names a snapshot it keeps: a path below its root."""


class KeptSnapshot(Identifiable, Trackable):
    """One snapshot a session keeps, under the snapshot's id. In the
    platform's bucket when it names no pool and is no VM's; in the
    store of the VMs' backend when `vm` says so, which knows it
    by `reference` and holds its disk to `digest`; else in the store of the
    host `host_id` of the pool `pool_id`, which knows it by `reference` and
    declared `digest` of its bytes. `hash` is the one the step names."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = ()

    agent_session_id: UUID
    hash: str = Field(pattern=SNAPSHOT_HASH.pattern)
    size: int = Field(ge=0)
    pool_id: UUID | None = None
    host_id: UUID | None = None
    reference: str = Field(pattern=REFERENCE)
    digest: str | None = Field(default=None, pattern=DIGEST)
    vm: bool = False

    @model_validator(mode="after")
    def _a_host_names_its_place(self) -> KeptSnapshot:
        if self.vm:
            if self.pool_id is not None or self.host_id is not None or self.digest is None:
                raise ValueError("a VM's snapshot names its digest, and no pool or host")
            return self
        hosted = (self.pool_id, self.host_id, self.digest)
        if any(part is None for part in hosted) and any(part is not None for part in hosted):
            raise ValueError("a snapshot a host keeps names its pool, its host, and its digest")
        return self

    @property
    def on_host(self) -> bool:
        """Whether a host inside the tenant's wall keeps it."""
        return self.pool_id is not None

    @property
    def on_vms(self) -> bool:
        """Whether the VMs' backend keeps it: a VM of the cloud
        pool's whole disk."""
        return self.vm


class HostSnapshot(OmBase):
    """A snapshot as a host is asked to keep it, or to start a workspace from
    it: its id, and, once kept, the reference its store knows it by, the
    digest of its bytes, their size, and the host that kept it
    (`kept_by`). Nothing of its content."""

    id: UUID
    reference: str | None = Field(default=None, pattern=REFERENCE)
    digest: str | None = Field(default=None, pattern=DIGEST)
    size: int | None = Field(default=None, ge=0)
    kept_by: UUID | None = None
