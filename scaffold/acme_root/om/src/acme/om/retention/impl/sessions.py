"""The engine's agent sessions, each created with its retention snapshot.

A decorator over the engine's sessions manager, behind the same interface.
A create takes the session's snapshot first, so no session is ever
written without one. Then the engine writes the session, and a session
whose policy keeps nothing at rest has the engine's memory-only storage
chosen for it before its history begins. Every other operation is the
engine's, unchanged."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import (
    AgentSession,
    AgentSessionPage,
    AgentSessionStatus,
    Among,
)
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agent_steps.types.header import Park, ParkReason
from acme.om.attribution.types.authority import Visibility
from acme.om.attribution.types.principal import AgentRef
from acme.om.context import TenantContext
from acme.om.exceptions import NotFound
from acme.om.privacy import PrivacyManagerInterface
from acme.om.privacy.types.agent_session_privacy import StorageMode, StoragePolicy
from acme.om.retention.manager import RetentionManagerInterface


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
        created = await self._inner.create_agent_session(ctx, session)
        if snapshot.policy.storage_mode is StorageMode.MEMORY_ONLY:
            await self._privacy.set_policy(
                ctx, created.id, StoragePolicy(mode=StorageMode.MEMORY_ONLY)
            )
        return created

    async def get_agent_session(self, ctx: TenantContext, agent_session_id: UUID) -> AgentSession:
        return await self._inner.get_agent_session(ctx, agent_session_id)

    async def get_agent_session_at_head(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSession:
        return await self._inner.get_agent_session_at_head(ctx, agent_session_id)

    async def get_children(
        self, ctx: TenantContext, parent_id: UUID, after: UUID | None, limit: int
    ) -> AgentSessionPage:
        return await self._inner.get_children(ctx, parent_id, after, limit)

    async def get_ancestors(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> tuple[AgentRef, ...]:
        return await self._inner.get_ancestors(ctx, agent_session_id)

    async def get_sessions(
        self,
        ctx: TenantContext,
        status: AgentSessionStatus | None,
        after: UUID | None,
        limit: int,
        among: Among = Among.VISIBLE,
    ) -> AgentSessionPage:
        return await self._inner.get_agent_sessions(ctx, status, after, limit, among)

    async def is_visible(self, ctx: TenantContext, agent_session_id: UUID) -> bool:
        return await self._inner.is_visible(ctx, agent_session_id)

    async def add_participant(
        self, ctx: TenantContext, agent_session_id: UUID, user_id: UUID
    ) -> AgentSession:
        return await self._inner.add_participant(ctx, agent_session_id, user_id)

    async def remove_participant(
        self, ctx: TenantContext, agent_session_id: UUID, user_id: UUID
    ) -> AgentSession:
        return await self._inner.remove_participant(ctx, agent_session_id, user_id)

    async def switch_visibility(
        self, ctx: TenantContext, agent_session_id: UUID, visibility: Visibility
    ) -> AgentSession:
        return await self._inner.switch_visibility(ctx, agent_session_id, visibility)

    async def project_status(self, ctx: TenantContext, agent_session_id: UUID) -> AgentSession:
        return await self._inner.project_status(ctx, agent_session_id)

    async def receive(
        self, ctx: TenantContext, agent_session_id: UUID, inputs: Sequence[AgentStep]
    ) -> tuple[tuple[AgentStep, ...], AgentSession]:
        return await self._inner.receive(ctx, agent_session_id, inputs)

    async def park(
        self, ctx: TenantContext, agent_session_id: UUID, epoch: int, loop_id: UUID, park: Park
    ) -> AgentSession:
        return await self._inner.park(ctx, agent_session_id, epoch, loop_id, park)

    async def resume(
        self, ctx: TenantContext, agent_session_id: UUID, epoch: int, loop_id: UUID
    ) -> AgentSession:
        return await self._inner.resume(ctx, agent_session_id, epoch, loop_id)

    async def wake_agent_session(
        self, ctx: TenantContext, agent_session_id: UUID, park: Park
    ) -> AgentSession:
        return await self._inner.wake_agent_session(ctx, agent_session_id, park)

    async def wake_parked(
        self, ctx: TenantContext, reason: ParkReason, unlock: str | None = None
    ) -> int:
        return await self._inner.wake_parked(ctx, reason, unlock)

    async def archive_agent_session(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSession:
        return await self._inner.archive_agent_session(ctx, agent_session_id)

    async def delete_agent_session(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSession:
        return await self._inner.delete_agent_session(ctx, agent_session_id)

    async def restore_agent_session(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSession:
        """The engine's restore, but for a session the sweep marked because
        its shape outlived its policy: that delete is final, and the session
        answers as one gone."""
        try:
            snapshot = await self._retention.get_snapshot(ctx, agent_session_id)
        except NotFound:
            snapshot = None
        if snapshot is not None and snapshot.shape_expired_at is not None:
            raise NotFound(f"agent session {agent_session_id} not found")
        return await self._inner.restore_agent_session(ctx, agent_session_id)

    async def purge_across_tenants(self) -> int:
        return await self._inner.purge_across_tenants()

    async def pending_across_tenants(
        self, after: datetime, before: datetime, limit: int
    ) -> list[tuple[UUID, AgentSession]]:
        return await self._inner.pending_across_tenants(after, before, limit)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        return await self._inner.purge_tenant(ctx)
