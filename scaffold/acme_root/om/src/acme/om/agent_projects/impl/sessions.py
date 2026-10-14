"""The engine's agent sessions, each spawned or handed over in the agent project
of the session it came from.

A decorator over the engine's sessions manager, behind the same interface.
A create of a session that came from another writes its agent project row first,
the one of the session it came from, so a child or a hand-over never stands
outside its origin's agent project, and so never under its tenant's looser
policies. A root session's row is written before it by the agent projects'
start, or never. Every other operation is the engine's, unchanged."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.om.agent_projects.exceptions import AgentProjectFixed
from acme.om.agent_projects.storage import AgentProjectStorageInterface
from acme.om.agent_projects.types.binding import SessionAgentProject
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import (
    AgentSession,
    AgentSessionPage,
    Among,
    SessionStatus,
)
from acme.om.attribution.types.authority import Visibility
from acme.om.attribution.types.principal import AgentRef
from acme.om.context import TenantContext
from acme.om.steps.types.header import Park, ParkReason
from acme.om.steps.types.step import Step


async def bind(
    storage: AgentProjectStorageInterface,
    org_id: UUID,
    session_id: UUID,
    agent_project_id: UUID,
    now: datetime,
) -> SessionAgentProject:
    """The session's agent project row, written once. Bound again to the same
    agent project, the row stands; to another, `AgentProjectFixed`."""
    stored = await storage.bind_session(
        org_id,
        SessionAgentProject(id=session_id, created_at=now, agent_project_id=agent_project_id),
    )
    if stored.agent_project_id != agent_project_id:
        raise AgentProjectFixed(
            f"agent session {session_id} belongs to agent project {stored.agent_project_id}"
        )
    return stored


class AgentSessionsInAgentProjectImpl(AgentSessionsManagerInterface):
    def __init__(
        self, inner: AgentSessionsManagerInterface, storage: AgentProjectStorageInterface
    ) -> None:
        self._inner = inner
        self._storage = storage

    async def create_session(self, ctx: TenantContext, session: AgentSession) -> AgentSession:
        """The origin's agent project row for the new session, then the session.
        An origin of no agent project, or one the tenant does not hold, writes
        nothing here, and the engine answers for the origin; a new session
        that names an agent project of its own then is `AgentProjectFixed`, since it
        belongs where its origin does."""
        came_from = session.parent_id or session.handed_off_from
        if came_from is not None:
            origin = await self._storage.read_binding(ctx.org_id, came_from)
            if origin is not None:
                await bind(
                    self._storage,
                    ctx.org_id,
                    session.id,
                    origin.agent_project_id,
                    session.created_at,
                )
            elif (own := await self._storage.read_binding(ctx.org_id, session.id)) is not None:
                raise AgentProjectFixed(
                    f"agent session {session.id} belongs to agent project {own.agent_project_id},"
                    f" and the session it came from to none"
                )
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
        among: Among = Among.VISIBLE,
    ) -> AgentSessionPage:
        return await self._inner.get_sessions(ctx, status, after, limit, among)

    async def is_visible(self, ctx: TenantContext, session_id: UUID) -> bool:
        return await self._inner.is_visible(ctx, session_id)

    async def add_participant(
        self, ctx: TenantContext, session_id: UUID, user_id: UUID
    ) -> AgentSession:
        return await self._inner.add_participant(ctx, session_id, user_id)

    async def remove_participant(
        self, ctx: TenantContext, session_id: UUID, user_id: UUID
    ) -> AgentSession:
        return await self._inner.remove_participant(ctx, session_id, user_id)

    async def switch_visibility(
        self, ctx: TenantContext, session_id: UUID, visibility: Visibility
    ) -> AgentSession:
        return await self._inner.switch_visibility(ctx, session_id, visibility)

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

    async def wake_parked(
        self, ctx: TenantContext, reason: ParkReason, unlock: str | None = None
    ) -> int:
        return await self._inner.wake_parked(ctx, reason, unlock)

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
