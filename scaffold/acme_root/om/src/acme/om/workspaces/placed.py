"""Where a session's workspace is made when the session runs inside its
tenant's wall: on a host of its pool, which prepares it and holds it from
then on. The exec relay answers it (`acme.om.exec_relay.impl.workspaces`); a root
that wires none makes every workspace on the machine it runs on.

A run that validates such a session's delivery makes an instance of its
own on a host of the same pool, and destroys it when the run ends. The
exec relay answers that too (`acme.om.exec_relay.impl.instances`); a root that wires
none refuses the run."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.infra.transports import TransportInterface
from acme.infra.workspaces import IsolationSpec, Workspace
from acme.om.context import TenantContext
from acme.om.hosts.types.placement import PlacementState
from acme.om.workspaces.types.snapshot import HostSnapshot


class PlacedWorkspacesInterface(ABC):
    @abstractmethod
    async def pool_of(self, ctx: TenantContext, session_id: UUID) -> UUID | None:
        """The host pool the session is pinned to; None for a session of the
        cloud."""
        ...

    @abstractmethod
    async def held_on_host(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spec: IsolationSpec,
        restore: HostSnapshot | None = None,
        *,
        pooled: PlacementState | None = None,
    ) -> Workspace | None:
        """The session's workspace, at its pinned `spec`, on the host of its
        pool that holds it; None for a session of the cloud, which this
        process prepares itself. With `pooled`, the session's pool of one in
        the cloud pool, it is the workspace the host of the session's
        machine holds: the pool keeps the machine's snapshots, never its
        host, so no host of it is asked to advertise any. `IsolationRefused` while no live host of
        its pool holds it: a host of the pool is asked to prepare it, and
        the loop waits on the resource with no call spent. A workspace kept
        by snapshots waits, with the reason, while no live host of its pool
        advertises snapshots at its level, and never runs as a cache. One
        on a base starts from the base its host builds and keeps; one whose
        base failed to build there waits with the host's reason.

        With `restore`, a snapshot a host's store keeps, the workspace is
        started from it, replaced whole: by the host that holds it while it
        is not revoked, or, with none, by a host of the pool whose store
        keeps it, which then holds it. The restore is asked before anything
        else and travels with the ask; the call waits for it a while, then
        the loop waits on the resource. `WorkspaceLost` when the host that
        holds the workspace lost it, or when no live host keeps it."""
        ...

    @abstractmethod
    async def snapshot_on_host(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spec: IsolationSpec,
        snapshot_id: UUID,
        *,
        kept_for: UUID | None = None,
    ) -> UUID:
        """Asks the host that holds the session's workspace to keep a snapshot
        of it in its own store under `snapshot_id`; the work's id. With
        `kept_for`, a fork's child, the host keeps the copy as that child's,
        where no erase of the session's snapshots reaches it. Its bytes
        never leave the host: the platform records the reference and the
        digest the host answers, under the session. `SnapshotRefused` when
        no live host holds the workspace."""
        ...

    @abstractmethod
    async def refusal_of(self, ctx: TenantContext, item_id: UUID) -> str | None:
        """Why the work under `item_id` failed; None while it waits or runs,
        and once it is done."""
        ...

    @abstractmethod
    async def erase_on_host(self, ctx: TenantContext, session_id: UUID, host_id: UUID) -> None:
        """Asks the host whose store keeps snapshots of the session to let
        every one go."""
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
