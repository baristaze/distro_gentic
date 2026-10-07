"""A pinned session's workspace, as the runner finds it: on the host of its
pool that prepared it, and nowhere else. Until one holds it, a host of the
pool is asked to prepare it, and the loop waits on the resource: each
refusal here clears once a host comes, so nothing is made on one of the
platform's machines in its stead, and no call is spent on a loop that
cannot run."""

from collections.abc import Callable
from uuid import UUID

from acme.infra.workspaces import IsolationRefused, IsolationSpec, Workspace
from acme.om.context import TenantContext
from acme.om.hosts import HostsManagerInterface
from acme.om.relay.manager import RelayManagerInterface
from acme.om.workspaces.placed import PlacedWorkspacesInterface


class PlacedWorkspacesRelayedImpl(PlacedWorkspacesInterface):
    """`relay` answers at call time, as the root builds the relay after the
    tools."""

    def __init__(
        self, relay: Callable[[], RelayManagerInterface], hosts: Callable[[], HostsManagerInterface]
    ) -> None:
        self._relay = relay
        self._hosts = hosts

    async def held_on_host(
        self, ctx: TenantContext, session_id: UUID, spec: IsolationSpec
    ) -> Workspace | None:
        placed = await self._hosts().placement_of(ctx, session_id)
        if placed.pool is None:
            return None
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
                return Workspace(
                    id=session_id, org_id=ctx.org_id, spec=spec, location=binding.location
                )
            # Its host was revoked or moved, and took the workspace with it:
            # another host of the pool prepares one.
        await self._relay().ask_prepare(ctx, session_id, spec)
        raise IsolationRefused(
            f"no host of pool {placed.pool.name} holds session {session_id}'s workspace yet "
            f"({placed.hosts_online} online); one prepares it when it claims the work",
            clears=True,
        )
