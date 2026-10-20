"""An instance a run makes inside a pinned session's wall: a new workspace
under an id of its own, made by a host of the session's pool, reached
through the exec relay, and destroyed when the run ends. The fresh executor
runs a pinned session's checks on one, never on the platform's VMs
and never in the session's own workspace."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID

from acme.infra.agent_workspaces import AgentWorkspace, IsolationSpec
from acme.infra.transports import TransportInterface
from acme.om.agent_workspaces.placed import PlacedInstancesInterface
from acme.om.base import utcnow
from acme.om.context import RequestContext, TenantContext
from acme.om.exceptions import Unavailable
from acme.om.exec_relay.manager import ExecRelayManagerInterface
from acme.timing import Retries, RetryPolicy

Relayed = Callable[[Callable[[], RequestContext]], TransportInterface]
"""The exec relay's transport, each operation of which runs under the stage it
is given: the root wires it over the exec relay."""


class PlacedInstancesRelayedImpl(PlacedInstancesInterface):
    """`exec_relay` answers at call time, as the root builds the exec relay after the
    evidence. While no host of the pool has made the instance, its binding
    is read again, at a wait that doubles from `first_poll` to `last_poll`.
    The instance is reached through `transport`, under the run's own
    stage."""

    def __init__(
        self,
        exec_relay: Callable[[], ExecRelayManagerInterface],
        transport: Relayed,
        *,
        first_poll: timedelta = timedelta(milliseconds=50),
        last_poll: timedelta = timedelta(seconds=1),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._exec_relay = exec_relay
        self._transport = transport
        self._poll = RetryPolicy(base=first_poll.total_seconds(), cap=last_poll.total_seconds())
        self._sleep = sleep
        self._clock = clock

    async def make(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        instance_id: UUID,
        spec: IsolationSpec,
        by: datetime,
    ) -> tuple[AgentWorkspace, TransportInterface]:
        relay = self._exec_relay()
        await relay.ask_instance(ctx, agent_session_id, instance_id, spec)
        polls = Retries(self._poll)
        while (binding := await relay.binding_of(ctx, instance_id)) is None:
            left = (by - self._clock()).total_seconds()
            if left <= 0:
                raise Unavailable(
                    f"no host of session {agent_session_id}'s pool made an instance for its run in time"
                )
            await self._sleep(min(polls.failed(), left))
        workspace = AgentWorkspace(
            id=instance_id, org_id=ctx.org_id, spec=spec, location=binding.location
        )
        return workspace, self._transport(lambda: ctx)

    async def destroy(self, ctx: TenantContext, instance_id: UUID, spec: IsolationSpec) -> None:
        relay = self._exec_relay()
        await relay.ask_purge(ctx, instance_id, spec)
        await relay.purge_agent_session(ctx.org_id, instance_id)
