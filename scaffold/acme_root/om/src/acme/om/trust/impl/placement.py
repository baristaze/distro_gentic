from uuid import UUID

from acme.om.trust.placement import PlacementInterface
from acme.om.trust.types.identities import Executor, ExecutorKind


class PlacementCloudImpl(PlacementInterface):
    """Every session in the platform's cloud, its calls run by the one
    machine it is built for: the default until hosts place a session inside
    a customer's wall."""

    def __init__(self, executor: Executor) -> None:
        if executor.kind is not ExecutorKind.CLOUD:
            raise ValueError("a session in the cloud runs on a machine of the cloud")
        self._executor = executor

    async def inside_wall(self, org_id: UUID, session_id: UUID) -> bool:
        return False

    async def executor_of(self, org_id: UUID, session_id: UUID) -> Executor:
        return self._executor
