"""The engine's agent sessions, each spawned or handed over in the project
of the session it came from.

A decorator over the engine's sessions manager, behind the same interface.
A create of a session that came from another writes its project row first,
the one of the session it came from, so a child or a hand-over never stands
outside its origin's project, and so never under its tenant's looser
policies. A root session's row is written before it by the projects'
start, or never. Every other operation is the engine's, unchanged."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import (
    AgentSession,
    AgentSessionPage,
    SessionStatus,
)
from acme.om.context import TenantContext
from acme.om.projects.exceptions import ProjectFixed
from acme.om.projects.storage import ProjectStorageInterface
from acme.om.projects.types.binding import SessionProject
from acme.om.steps.types.header import Park, ParkReason
from acme.om.steps.types.step import Step


async def bind(
    storage: ProjectStorageInterface,
    org_id: UUID,
    session_id: UUID,
    project_id: UUID,
    now: datetime,
) -> SessionProject:
    """The session's project row, written once. Bound again to the same
    project, the row stands; to another, `ProjectFixed`."""
    stored = await storage.bind_session(
        org_id, SessionProject(id=session_id, created_at=now, project_id=project_id)
    )
    if stored.project_id != project_id:
        raise ProjectFixed(f"agent session {session_id} belongs to project {stored.project_id}")
    return stored


class AgentSessionsInProjectImpl(AgentSessionsManagerInterface):
    def __init__(
        self, inner: AgentSessionsManagerInterface, storage: ProjectStorageInterface
    ) -> None:
        self._inner = inner
        self._storage = storage

    async def create_session(self, ctx: TenantContext, session: AgentSession) -> AgentSession:
        """The origin's project row for the new session, then the session.
        An origin of no project, or one the tenant does not hold, writes
        nothing here, and the engine answers for the origin; a new session
        that names a project of its own then is `ProjectFixed`, since it
        belongs where its origin does."""
        came_from = session.parent_id or session.handed_off_from
        if came_from is not None:
            origin = await self._storage.read_binding(ctx.org_id, came_from)
            if origin is not None:
                await bind(
                    self._storage, ctx.org_id, session.id, origin.project_id, session.created_at
                )
            elif (own := await self._storage.read_binding(ctx.org_id, session.id)) is not None:
                raise ProjectFixed(
                    f"agent session {session.id} belongs to project {own.project_id},"
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

    async def purge_tenant(self, ctx: TenantContext) -> int:
        return await self._inner.purge_tenant(ctx)
