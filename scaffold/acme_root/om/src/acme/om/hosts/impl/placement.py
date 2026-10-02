from uuid import UUID

from acme.om.hosts.exceptions import PinnedToHosts
from acme.om.hosts.storage import HostsStorageInterface
from acme.om.trust.placement import PlacementInterface
from acme.om.trust.types.identities import Executor, ExecutorKind


class PlacementHostsImpl(PlacementInterface):
    """Trust's question of where a session runs, answered from the hosts'
    placement. A session no principal pinned runs in the cloud, on the one
    machine this is built for. A pinned session runs inside its tenant's
    wall, on a host of its pool, which only the relay reaches: until a call
    names the host that holds its workspace, it is refused, and it never
    runs on one of the platform's machines."""

    def __init__(self, storage: HostsStorageInterface, cloud: Executor) -> None:
        if cloud.kind is not ExecutorKind.CLOUD:
            raise ValueError("a session in the cloud runs on a machine of the cloud")
        self._storage = storage
        self._cloud = cloud

    async def inside_wall(self, org_id: UUID, session_id: UUID) -> bool:
        placed = await self._storage.read_placement(org_id, session_id)
        return placed is not None and placed.pool_id is not None

    async def executor_of(self, org_id: UUID, session_id: UUID) -> Executor:
        if not await self.inside_wall(org_id, session_id):
            return self._cloud
        raise PinnedToHosts(
            f"session {session_id} is pinned to its tenant's hosts, and no host holds "
            "its workspace yet; its calls never run on the platform's machines"
        )
