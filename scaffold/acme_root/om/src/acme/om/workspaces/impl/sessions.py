"""The engine's agent sessions, each created with its workspace pinned.

A decorator over the engine's sessions manager, behind the same interface.
A create pins the session's isolation first, so no session is written
without one, and a create retried under the same id meets the pin already
there. Whether the session keeps content at rest is read first, by the
policy its retention will take (`at_rest`): one that keeps none is refused
a workspace kept by snapshots. Every other operation is the engine's,
unchanged."""

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from uuid import UUID

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import (
    AgentSession,
    AgentSessionPage,
    SessionStatus,
)
from acme.om.attribution.types.principal import AgentRef
from acme.om.context import TenantContext
from acme.om.steps.types.header import Park, ParkReason
from acme.om.steps.types.step import Step
from acme.om.workspaces.manager import WorkspacesManagerInterface

AtRest = Callable[[TenantContext, AgentSession], Awaitable[bool]]
"""Whether a session about to be created keeps its content at rest."""


class AgentSessionsPinnedImpl(AgentSessionsManagerInterface):
    def __init__(
        self,
        inner: AgentSessionsManagerInterface,
        workspaces: WorkspacesManagerInterface,
        at_rest: AtRest | None = None,
    ) -> None:
        self._inner = inner
        self._workspaces = workspaces
        self._at_rest = at_rest

    async def create_session(self, ctx: TenantContext, session: AgentSession) -> AgentSession:
        at_rest = True if self._at_rest is None else await self._at_rest(ctx, session)
        await self._workspaces.pin(ctx, session, at_rest=at_rest)
        return await self._inner.create_session(ctx, session)

    async def get_session(self, ctx: TenantContext, session_id: UUID) -> AgentSession:
        return await self._inner.get_session(ctx, session_id)

    async def get_session_at_head(self, ctx: TenantContext, session_id: UUID) -> AgentSession:
        return await self._inner.get_session_at_head(ctx, session_id)

    async def get_children(
        self, ctx: TenantContext, parent_id: UUID, after: UUID | None, limit: int
    ) -> AgentSessionPage:
        return await self._inner.get_children(ctx, parent_id, after, limit)

    async def get_ancestors(self, ctx: TenantContext, session_id: UUID) -> tuple[AgentRef, ...]:
        return await self._inner.get_ancestors(ctx, session_id)

    async def get_sessions(
        self,
        ctx: TenantContext,
        status: SessionStatus | None,
        after: UUID | None,
        limit: int,
    ) -> AgentSessionPage:
        return await self._inner.get_sessions(ctx, status, after, limit)

    async def project_status(self, ctx: TenantContext, session_id: UUID) -> AgentSession:
        return await self._inner.project_status(ctx, session_id)

    async def receive(
        self, ctx: TenantContext, session_id: UUID, inputs: Sequence[Step]
    ) -> tuple[tuple[Step, ...], AgentSession]:
        return await self._inner.receive(ctx, session_id, inputs)

    async def park(
        self, ctx: TenantContext, session_id: UUID, epoch: int, loop_id: UUID, park: Park
    ) -> AgentSession:
        return await self._inner.park(ctx, session_id, epoch, loop_id, park)

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
