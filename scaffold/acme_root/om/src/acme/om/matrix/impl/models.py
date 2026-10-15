"""The engine's models manager as the matrix serves it. A session's fills
are resolved within what its tenant's retention requires; at the start of
each loop a fill whose model was retired, or that the retention no longer
admits, switches; a fallback the retention no longer admits is never taken;
and each switch the matrix makes pins the version it came from. Everything
else is the engine's."""

from collections.abc import Callable, Collection, Sequence
from datetime import datetime
from uuid import UUID

from acme.om.base import new_id, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import NotFound, UnresolvedRole, ValidationFailed
from acme.om.language_models.manager import LanguageModelsManagerInterface
from acme.om.language_models.types.fill import (
    Eligibility,
    Fill,
    FillSet,
    FillSwitch,
    ModelAsk,
    ModelRole,
    SwitchReason,
)
from acme.om.matrix import rules
from acme.om.matrix.impl.resolver import MatrixOptions
from acme.om.matrix.resolver import MatrixResolverInterface
from acme.om.matrix.storage import MatrixTenantStorageInterface
from acme.om.matrix.types.tenant import MatrixPin
from acme.om.retention.storage import RetentionStorageInterface
from acme.om.tenancy import TenancyManagerInterface


class ModelsManagerMatrixImpl(LanguageModelsManagerInterface):
    def __init__(
        self,
        inner: LanguageModelsManagerInterface,
        resolver: MatrixResolverInterface,
        tenants: MatrixTenantStorageInterface,
        retention: RetentionStorageInterface,
        tenancy: TenancyManagerInterface,
        options: MatrixOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._inner = inner
        self._resolver = resolver
        self._tenants = tenants
        self._retention = retention
        self._tenancy = tenancy
        self._options = options
        self._clock = clock

    async def resolve_fill_set(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        roles: Sequence[ModelRole],
        eligibility: Eligibility,
        asks: Sequence[ModelAsk] = (),
    ) -> FillSet:
        ctx.require(Permission.WRITE)
        try:
            return await self._inner.get_fill_set(ctx, agent_session_id)
        except NotFound:
            pass
        # The first resolution: every fill and every fallback within what the
        # tenant's retention requires, kept on the fill set, so a fallback
        # or a switch later meets it too.
        required = await self._required(ctx, agent_session_id, eligibility)
        return await self._inner.resolve_fill_set(ctx, agent_session_id, roles, required, asks)

    async def renew_fill_set(
        self, ctx: TenantContext, agent_session_id: UUID, epoch: int, loop_id: UUID
    ) -> FillSet:
        ctx.require(Permission.WRITE)
        head = await self._inner.renew_fill_set(ctx, agent_session_id, epoch, loop_id)
        # The retention as the session holds it now: a tightening since its
        # fills were resolved reaches them here, between loops.
        required = await self._required(ctx, agent_session_id, head.eligibility)
        renewal = await self._resolver.renewal(ctx, agent_session_id, head, required)
        if renewal is None:
            return head
        number, switches = renewal
        for role, to, reason in switches:
            head = await self._inner.switch_fill(
                ctx, agent_session_id, epoch, loop_id, role, to, reason
            )
        await self._tenants.write_pin(
            ctx.org_id,
            MatrixPin(
                id=new_id(),
                created_at=self._clock(),
                agent_session_id=agent_session_id,
                fill_set_version=head.version,
                matrix_version=number,
            ),
        )
        return head

    async def get_fill_set(self, ctx: TenantContext, agent_session_id: UUID) -> FillSet:
        return await self._inner.get_fill_set(ctx, agent_session_id)

    async def switch_fill(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        epoch: int,
        loop_id: UUID,
        role: ModelRole,
        to: Fill,
        reason: SwitchReason,
    ) -> FillSet:
        head = await self._inner.get_fill_set(ctx, agent_session_id)
        required = await self._required(ctx, agent_session_id, head.eligibility)
        if not required.admits(to.eligibility):
            raise ValidationFailed(f"{to.name} does not meet the session's retention")
        return await self._inner.switch_fill(
            ctx, agent_session_id, epoch, loop_id, role, to, reason
        )

    async def fall_back(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        epoch: int,
        loop_id: UUID,
        role: ModelRole,
        tried: Collection[Fill] = (),
    ) -> FillSet | None:
        head = await self._inner.get_fill_set(ctx, agent_session_id)
        required = await self._required(ctx, agent_session_id, head.eligibility)
        found = head.role_fill(role)
        # A fallback a tightening of the retention no longer admits is never
        # taken: it counts as tried.
        barred = (
            ()
            if found is None
            else tuple(fill for fill in found.fallbacks if not required.admits(fill.eligibility))
        )
        return await self._inner.fall_back(
            ctx, agent_session_id, epoch, loop_id, role, (*tried, *barred)
        )

    async def settle_switch(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        agent_step_id: UUID,
        fills: FillSwitch,
        at: datetime,
    ) -> FillSet:
        return await self._inner.settle_switch(ctx, agent_session_id, agent_step_id, fills, at)

    async def _required(
        self, ctx: TenantContext, agent_session_id: UUID, eligibility: Eligibility
    ) -> Eligibility:
        """What the session requires of every fill: the tighter of
        `eligibility` and its retention snapshot. A session with no snapshot
        resolves to nothing, and neither does one that requires two
        regions."""
        snapshot = await self._retention.read_snapshot(ctx.org_id, agent_session_id)
        if snapshot is None:
            raise UnresolvedRole(
                f"session {agent_session_id} has no retention snapshot to resolve within"
            )
        required = rules.required(eligibility, snapshot.policy)
        if required is None:
            raise UnresolvedRole(f"session {agent_session_id} requires two regions at once")
        return required

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        mine = await self._tenants.purge_tenant(ctx.org_id, self._options.purge_batch)
        return mine + await self._inner.purge_tenant(ctx)
