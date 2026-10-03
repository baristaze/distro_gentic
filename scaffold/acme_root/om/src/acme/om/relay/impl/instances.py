"""An instance a run makes inside a pinned session's wall: a new workspace
under an id of its own, made by a host of the session's pool, reached
through the relay, and destroyed when the run ends. The fresh executor
runs a pinned session's checks on one, never on the platform's machines
and never in the session's own workspace."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID

from acme.infra.transports import TransportInterface
from acme.infra.workspaces import IsolationSpec, Workspace
from acme.om.base import utcnow
from acme.om.context import RequestContext, TenantContext
from acme.om.exceptions import Unavailable
from acme.om.relay.manager import RelayManagerInterface
from acme.om.workspaces.placed import PlacedInstancesInterface

Relayed = Callable[[Callable[[], RequestContext]], TransportInterface]
"""The relay's transport, each operation of which runs under the stage it
is given: the root wires it over the relay."""


class PlacedInstancesRelayedImpl(PlacedInstancesInterface):
    """`relay` answers at call time, as the root builds the relay after the
    evidence. While no host of the pool has made the instance, its binding
    is read again, at a wait that doubles from `first_poll` to `last_poll`.
    The instance is reached through `transport`, under the run's own
    stage."""

    def __init__(
        self,
        relay: Callable[[], RelayManagerInterface],
        transport: Relayed,
        *,
        first_poll: timedelta = timedelta(milliseconds=50),
        last_poll: timedelta = timedelta(seconds=1),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._relay = relay
        self._transport = transport
        self._first_poll = first_poll
        self._last_poll = last_poll
        self._sleep = sleep
        self._clock = clock

    async def make(
        self,
        ctx: TenantContext,
        session_id: UUID,
        instance_id: UUID,
        spec: IsolationSpec,
        by: datetime,
    ) -> tuple[Workspace, TransportInterface]:
        relay = self._relay()
        await relay.ask_instance(ctx, session_id, instance_id, spec)
        wait = self._first_poll
        while (binding := await relay.binding_of(ctx, instance_id)) is None:
            left = (by - self._clock()).total_seconds()
            if left <= 0:
                raise Unavailable(
                    f"no host of session {session_id}'s pool made an instance for its run in time"
                )
            await self._sleep(min(wait.total_seconds(), left))
            wait = min(wait * 2, self._last_poll)
        workspace = Workspace(
            id=instance_id, org_id=ctx.org_id, spec=spec, location=binding.location
        )
        return workspace, self._transport(lambda: ctx)

    async def destroy(self, ctx: TenantContext, instance_id: UUID, spec: IsolationSpec) -> None:
        relay = self._relay()
        await relay.ask_purge(ctx, instance_id, spec)
        await relay.purge_session(ctx.org_id, instance_id)
