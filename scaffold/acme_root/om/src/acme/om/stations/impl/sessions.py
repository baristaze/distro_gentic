"""The engine's agent sessions, each one that parks on a station's line
offered the stations that serve it.

A decorator over the engine's sessions manager, behind the same interface.
A session that joins a line while its loop runs keeps its place and is
passed over until it parks; its park on the line is the moment it waits,
so the park offers every station that serves a line it stands in, and a
free one goes to the first in that line who waits. Every other operation
is the engine's, unchanged."""

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from uuid import UUID

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import (
    AgentSession,
    AgentSessionPage,
    SessionStatus,
)
from acme.om.context import TenantContext
from acme.om.stations.rules import LINE_PARK
from acme.om.stations.types.lease import StationLease
from acme.om.steps.types.header import Park, ParkReason
from acme.om.steps.types.step import Step

Offer = Callable[[TenantContext, UUID], Awaitable[StationLease | None]]
"""Offers the stations of every line a session stands in; the lease it was
granted, if it was."""


class AgentSessionsInLineImpl(AgentSessionsManagerInterface):
    def __init__(self, inner: AgentSessionsManagerInterface, offer: Offer) -> None:
        self._inner = inner
        self._offer = offer

    async def park(
        self, ctx: TenantContext, session_id: UUID, epoch: int, loop_id: UUID, park: Park
    ) -> AgentSession:
        parked = await self._inner.park(ctx, session_id, epoch, loop_id, park)
        if park != LINE_PARK or parked.status is not SessionStatus.PARKED:
            return parked
        if await self._offer(ctx, session_id) is None:
            return parked
        # The grant woke it: its status is the one the wake left.
        return await self._inner.get_session(ctx, session_id)

    async def create_session(self, ctx: TenantContext, session: AgentSession) -> AgentSession:
        return await self._inner.create_session(ctx, session)

    async def get_session(self, ctx: TenantContext, session_id: UUID) -> AgentSession:
        return await self._inner.get_session(ctx, session_id)

    async def get_session_at_head(self, ctx: TenantContext, session_id: UUID) -> AgentSession:
        return await self._inner.get_session_at_head(ctx, session_id)

    async def get_children(
        self, ctx: TenantContext, parent_id: UUID, after: UUID | None, limit: int
    ) -> AgentSessionPage:
        return await self._inner.get_children(ctx, parent_id, after, limit)

    async def get_sessions(
        self, ctx: TenantContext, status: SessionStatus | None, after: UUID | None, limit: int
    ) -> AgentSessionPage:
        return await self._inner.get_sessions(ctx, status, after, limit)

    async def project_status(self, ctx: TenantContext, session_id: UUID) -> AgentSession:
        return await self._inner.project_status(ctx, session_id)

    async def receive(
        self, ctx: TenantContext, session_id: UUID, inputs: Sequence[Step]
    ) -> tuple[tuple[Step, ...], AgentSession]:
        return await self._inner.receive(ctx, session_id, inputs)

    async def resume(
        self, ctx: TenantContext, session_id: UUID, epoch: int, loop_id: UUID
    ) -> AgentSession:
        return await self._inner.resume(ctx, session_id, epoch, loop_id)

    async def wake_session(self, ctx: TenantContext, session_id: UUID, park: Park) -> AgentSession:
        return await self._inner.wake_session(ctx, session_id, park)

    async def wake_parked(self, ctx: TenantContext, reason: ParkReason) -> int:
        return await self._inner.wake_parked(ctx, reason)

    async def archive_session(self, ctx: TenantContext, session_id: UUID) -> AgentSession:
        return await self._inner.archive_session(ctx, session_id)

    async def delete_session(self, ctx: TenantContext, session_id: UUID) -> AgentSession:
        return await self._inner.delete_session(ctx, session_id)

    async def restore_session(self, ctx: TenantContext, session_id: UUID) -> AgentSession:
        return await self._inner.restore_session(ctx, session_id)

    async def purge_across_tenants(self) -> int:
        return await self._inner.purge_across_tenants()

    async def pending_across_tenants(
        self, after: datetime, before: datetime, limit: int
    ) -> list[tuple[UUID, AgentSession]]:
        return await self._inner.pending_across_tenants(after, before, limit)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        return await self._inner.purge_tenant(ctx)
