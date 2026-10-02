"""Where a session runs: the platform's cloud, or one of its tenant's host
pools. A principal sets it, and nothing else changes it."""

from uuid import UUID

from pydantic import Field

from acme.om.base import Identifiable, Platform, Trackable
from acme.om.hosts.types.pool import HostPool


class SessionPlacement(Identifiable, Trackable):
    """One row a session that a principal placed; a session with none runs
    in the cloud. `pool_id` None is the cloud too, when a principal moved a
    pinned session back."""

    session_id: UUID
    pool_id: UUID | None = None
    version: int = Field(default=1, ge=1)


class PlacementState(Platform):
    """A session's placement as a person reads it: its pool, or the cloud,
    and how many of the pool's hosts are online. A pinned session with
    none online waits, and says so here; it never moves."""

    session_id: UUID
    pool: HostPool | None = None
    hosts_online: int = 0
    version: int = 0  # 0: never placed, so in the cloud

    @property
    def waiting(self) -> bool:
        return self.pool is not None and self.hosts_online == 0
