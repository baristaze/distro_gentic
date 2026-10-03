"""Where a session's workspace is made when the session runs inside its
tenant's wall: on a host of its pool, which prepares it and holds it from
then on. The relay answers it (`acme.om.relay.impl.workspaces`); a root
that wires none makes every workspace on the machine it runs on.

A run that validates such a session's delivery makes an instance of its
own on a host of the same pool, and destroys it when the run ends. The
relay answers that too (`acme.om.relay.impl.instances`); a root that wires
none refuses the run."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.infra.transports import TransportInterface
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


class PlacedInstancesInterface(ABC):
    @abstractmethod
    async def make(
        self,
        ctx: TenantContext,
        session_id: UUID,
        instance_id: UUID,
        spec: IsolationSpec,
        by: datetime,
    ) -> tuple[Workspace, TransportInterface]:
        """A new instance under `instance_id`, made to `spec` for one run by a
        host of the pool the session is pinned to, and the transport that
        reaches it, under the run's context. The instance is never the
        session's workspace, and no host outside the pool makes it.
        `Unavailable` when no host of the pool made it by `by`."""
        ...

    @abstractmethod
    async def destroy(self, ctx: TenantContext, instance_id: UUID, spec: IsolationSpec) -> None:
        """The instance goes, whatever its run came to: the host that holds
        it is asked to destroy it, or the prepare that waits for a host is
        ended, and what the platform kept of its commands goes now."""
        ...
