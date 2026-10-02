"""The engine's agent sessions, each created with its retention snapshot.

A decorator over the engine's sessions manager, behind the same interface.
A create takes the session's snapshot first, so no session is ever
written without one. Then the engine writes the session, and a session
whose policy keeps nothing at rest has the engine's memory-only storage
chosen for it before its history begins. Every other operation is the
engine's, unchanged."""

from collections.abc import Sequence
from uuid import UUID

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import (
    AgentSession,
    AgentSessionPage,
    SessionStatus,
)
from acme.om.context import TenantContext
from acme.om.exceptions import NotFound
from acme.om.privacy import PrivacyManagerInterface
from acme.om.privacy.types.session_privacy import StorageMode, StoragePolicy
from acme.om.retention.manager import RetentionManagerInterface
from acme.om.steps.types.header import Park, ParkReason
from acme.om.steps.types.step import Step


class AgentSessionsRetainedImpl(AgentSessionsManagerInterface):
    def __init__(
        self,
        inner: AgentSessionsManagerInterface,
        retention: RetentionManagerInterface,
        privacy: PrivacyManagerInterface,
    ) -> None:
        self._inner = inner
        self._retention = retention
        self._privacy = privacy

    async def create_session(self, ctx: TenantContext, session: AgentSession) -> AgentSession:
        """The snapshot, then the session, then its storage. Each step is safe
        to take again, so a create retried under the same id finishes what
        the first left."""
        snapshot = await self._retention.take_snapshot(ctx, session)
        created = await self._inner.create_session(ctx, session)
        if snapshot.policy.storage_mode is StorageMode.MEMORY_ONLY:
            await self._privacy.set_policy(
                ctx, created.id, StoragePolicy(mode=StorageMode.MEMORY_ONLY)
            )
        return created

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
        """The engine's restore, but for a session the sweep marked because
        its shape outlived its policy: that delete is final, and the session
        answers as one gone."""
        try:
            snapshot = await self._retention.get_snapshot(ctx, session_id)
        except NotFound:
            snapshot = None
        if snapshot is not None and snapshot.shape_expired_at is not None:
            raise NotFound(f"agent session {session_id} not found")
        return await self._inner.restore_session(ctx, session_id)

    async def purge_across_tenants(self) -> int:
        return await self._inner.purge_across_tenants()

    async def purge_tenant(self, ctx: TenantContext) -> int:
        return await self._inner.purge_tenant(ctx)
