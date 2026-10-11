"""A pinned session's workspace, as the runner finds it: on the host of its
pool that prepared it, and nowhere else. Until one holds it, a host of the
pool is asked to prepare it, and the loop waits on the resource: each
refusal here clears once a host comes, so nothing is made on one of the
platform's machines in its stead, and no call is spent on a loop that
cannot run.

A workspace kept by snapshots keeps them in the store of a host inside its
tenant's wall, never in the platform's: it waits, with the reason, while no
live host of its pool advertises snapshots at its level. A restore is
decided before any host is asked, and travels with the ask: the host that
holds the workspace, while it is not revoked, replaces it from its store,
and the session waits for it while it is offline; with none, a host of the
pool whose store keeps the snapshot makes it. The run waits for it a while,
then the loop waits on the resource; a snapshot no live host keeps loses
the workspace, with the reason. A snapshot is asked of the host that holds
the workspace, which keeps its bytes and answers its reference and its
digest. A workspace on a base starts from the base its host builds and
keeps in its own store; one whose base failed to build there waits with
the host's reason, its failing command and that command's exit code among
it."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID

from acme.infra.workspaces import (
    Durability,
    IsolationRefused,
    IsolationSpec,
    SnapshotRefused,
    Workspace,
    WorkspaceLost,
)
from acme.om.base import utcnow
from acme.om.context import TenantContext
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.rules import SNAPSHOTS, snapshots_advertised
from acme.om.hosts.types.host import IsolationMode as HostMode
from acme.om.hosts.types.placement import PlacementState
from acme.om.relay.manager import RelayManagerInterface
from acme.om.relay.rules import asks
from acme.om.relay.types.exec import WorkspaceBinding
from acme.om.work.types.work_item import WorkStatus
from acme.om.workspaces.placed import PlacedWorkspacesInterface
from acme.om.workspaces.types.snapshot import HostSnapshot


class PlacedWorkspacesRelayedImpl(PlacedWorkspacesInterface):
    """`relay` answers at call time, as the root builds the relay after the
    tools. A restore is waited on for `restore_wait`, its work read again at
    a wait that doubles from `first_poll` to `last_poll`."""

    def __init__(
        self,
        relay: Callable[[], RelayManagerInterface],
        hosts: Callable[[], HostsManagerInterface],
        *,
        restore_wait: timedelta = timedelta(minutes=5),
        first_poll: timedelta = timedelta(milliseconds=50),
        last_poll: timedelta = timedelta(seconds=1),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._relay = relay
        self._hosts = hosts
        self._restore_wait = restore_wait
        self._first_poll = first_poll
        self._last_poll = last_poll
        self._sleep = sleep
        self._clock = clock

    async def pool_of(self, ctx: TenantContext, session_id: UUID) -> UUID | None:
        placed = await self._hosts().placement_of(ctx, session_id)
        return None if placed.pool is None else placed.pool.id

    async def held_on_host(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spec: IsolationSpec,
        restore: HostSnapshot | None = None,
    ) -> Workspace | None:
        placed = await self._hosts().placement_of(ctx, session_id)
        if placed.pool is None:
            return None
        if spec.durability is Durability.SNAPSHOT:
            await self._snapshots_offered(ctx, placed, session_id, spec)
        if restore is not None:
            return await self._restored(ctx, placed, session_id, spec, restore)
        binding = await self._relay().binding_of(ctx, session_id)
        if binding is not None:
            holder = await self._hosts().get_host(ctx, placed.pool.id, binding.host_id)
            if holder is not None and holder.host.revoked_at is None:
                if not holder.online:
                    # A workspace lives where it was prepared: the session
                    # waits for its host, and never moves on a guess.
                    raise IsolationRefused(
                        f"host {binding.host_name}, which holds session {session_id}'s "
                        "workspace, is offline",
                        clears=True,
                    )
                return _held(ctx, session_id, spec, binding)
            # Its host was revoked or moved, and took the workspace with it:
            # another host of the pool prepares one.
        # Read before the ask: a prepare that failed is followed by a new
        # one, and the run still says why the last was refused.
        refused = await self._relay().prepare_refusal(ctx, session_id)
        await self._relay().ask_prepare(ctx, session_id, spec)
        why = "" if refused is None else f"; a host refused it: {refused}"
        raise IsolationRefused(
            f"no host of pool {placed.pool.name} holds session {session_id}'s workspace yet "
            f"({placed.hosts_online} online); one prepares it when it claims the work{why}",
            clears=True,
        )

    async def snapshot_on_host(
        self, ctx: TenantContext, session_id: UUID, spec: IsolationSpec, snapshot_id: UUID
    ) -> UUID:
        item_id = await self._relay().ask_snapshot(ctx, session_id, spec, snapshot_id)
        if item_id is None:
            raise SnapshotRefused(
                f"no live host holds session {session_id}'s workspace, so none snapshots it"
            )
        return item_id

    async def refusal_of(self, ctx: TenantContext, item_id: UUID) -> str | None:
        row = await self._relay().workspace_work(ctx, item_id)
        if row.status is not WorkStatus.FAILED:
            return None
        return row.last_error or "the host gave no reason"

    async def erase_on_host(self, ctx: TenantContext, session_id: UUID, host_id: UUID) -> None:
        await self._relay().ask_erase(ctx, session_id, host_id)

    async def _snapshots_offered(
        self, ctx: TenantContext, placed: PlacementState, session_id: UUID, spec: IsolationSpec
    ) -> None:
        """Refuses, until one comes, a workspace kept by snapshots in a pool
        where no live, online host advertises snapshots at its level: it
        waits, and is never prepared as a cache in its stead."""
        assert placed.pool is not None
        asked, _, _ = asks(spec, "")
        isolation = None if asked is None else HostMode(asked)
        if isolation is not None:
            hosts = await self._hosts().get_hosts(ctx, placed.pool.id)
            if any(
                status.online
                and status.host.revoked_at is None
                and snapshots_advertised(status.host, isolation)
                for status in hosts
            ):
                return
        level = spec.mode.value if isolation is None else isolation.value
        holds = "" if isolation is None else f", which would hold {SNAPSHOTS[isolation][1]}"
        raise IsolationRefused(
            f"session {session_id} keeps its workspace by snapshots, and no live host of pool "
            f"{placed.pool.name} has probed snapshots of a {level} workspace{holds}: it waits "
            "for one",
            clears=True,
        )

    async def _restored(
        self,
        ctx: TenantContext,
        placed: PlacementState,
        session_id: UUID,
        spec: IsolationSpec,
        restore: HostSnapshot,
    ) -> Workspace:
        """The workspace once a host restored it from `restore`."""
        assert placed.pool is not None
        relay = self._relay()
        item_id = await relay.ask_restore(ctx, session_id, spec, restore)
        by = self._clock() + self._restore_wait
        wait = self._first_poll
        while True:
            row = await relay.workspace_work(ctx, item_id)
            if row.status is WorkStatus.DONE:
                binding = await relay.binding_of(ctx, session_id)
                if binding is not None:
                    return _held(ctx, session_id, spec, binding)
            if row.status is WorkStatus.FAILED:
                raise WorkspaceLost(
                    f"snapshot {restore.id} of session {session_id} did not come back from its "
                    f"host's store: {row.last_error or 'the host gave no reason'}"
                )
            left = (by - self._clock()).total_seconds()
            if left <= 0:
                raise IsolationRefused(
                    f"no host of pool {placed.pool.name} has restored session {session_id}'s "
                    f"workspace from snapshot {restore.id} yet; one does when it claims the work",
                    clears=True,
                )
            await self._sleep(min(wait.total_seconds(), left))
            wait = min(wait * 2, self._last_poll)


def _held(
    ctx: TenantContext, session_id: UUID, spec: IsolationSpec, binding: WorkspaceBinding
) -> Workspace:
    return Workspace(id=session_id, org_id=ctx.org_id, spec=spec, location=binding.location)
