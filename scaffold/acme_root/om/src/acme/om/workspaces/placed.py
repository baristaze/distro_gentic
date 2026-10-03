"""Where a session's workspace is made when the session runs inside its
tenant's wall: on a host of its pool, which prepares it and holds it from
then on. The relay answers it (`acme.om.relay.impl.workspaces`); a root
that wires none makes every workspace on the machine it runs on."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.infra.workspaces import IsolationSpec, Workspace
from acme.om.context import TenantContext


class PlacedWorkspacesInterface(ABC):
    @abstractmethod
    async def held_on_host(
        self, ctx: TenantContext, session_id: UUID, spec: IsolationSpec
    ) -> Workspace | None:
        """The session's workspace, at its pinned `spec`, on the host of its
        pool that holds it; None for a session of the cloud, which this
        process prepares itself. `IsolationRefused` while no live host of
        its pool holds it: a host of the pool is asked to prepare it, and
        the loop waits on the resource with no call spent."""
        ...
