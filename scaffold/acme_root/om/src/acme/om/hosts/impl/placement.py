from uuid import UUID

from acme.om.agent_sessions.storage import AgentSessionStorageInterface
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
    runs on one of the platform's machines. A sub-agent runs where its
    tree's root runs: its placement is its root's."""

    def __init__(
        self,
        storage: HostsStorageInterface,
        sessions: AgentSessionStorageInterface,
        cloud: Executor,
    ) -> None:
        if cloud.kind is not ExecutorKind.CLOUD:
            raise ValueError("a session in the cloud runs on a machine of the cloud")
        self._storage = storage
        self._sessions = sessions
        self._cloud = cloud

    async def inside_wall(self, org_id: UUID, session_id: UUID) -> bool:
        return await inside_wall(self._storage, self._sessions, org_id, session_id)

    async def executor_of(self, org_id: UUID, session_id: UUID) -> Executor:
        if not await self.inside_wall(org_id, session_id):
            return self._cloud
        raise PinnedToHosts(
            f"session {session_id} is pinned to its tenant's hosts, and no host holds "
            "its workspace yet; its calls never run on the platform's machines"
        )


async def inside_wall(
    storage: HostsStorageInterface,
    sessions: AgentSessionStorageInterface,
    org_id: UUID,
    session_id: UUID,
) -> bool:
    """Whether a session runs inside its tenant's wall: its tree's root is
    pinned to a pool. A session no agent session is, such as a validation
    session, is its own root, and no principal pinned it."""
    session = await sessions.read_session(org_id, session_id)
    root_id = session_id if session is None else session.root_id
    placed = await storage.read_placement(org_id, root_id)
    return placed is not None and placed.pool_id is not None
