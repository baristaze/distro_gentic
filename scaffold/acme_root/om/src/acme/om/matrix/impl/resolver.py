"""The matrix as the engine's resolver: a session's fills answer the
question its kind, its tenant's plan tier, its workload class, and the
environment ask, at the version the session is pinned to. What the session
may not run on is filtered out first: a fill its eligibility does not
admit, a retired model, and, for a tenant on its own keys, a provider it
holds no key for."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError

from acme.integrations.model_providers.types import ProviderName
from acme.om.agent_sessions.storage import AgentSessionStorageInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.base import Platform, new_id, utcnow
from acme.om.billing.storage import AccountStorageInterface
from acme.om.billing.types.account import FundingMode
from acme.om.context import TenantContext
from acme.om.exceptions import NotFound, UnpricedModel, UnresolvedRole, ValidationFailed
from acme.om.matrix import rules
from acme.om.matrix.resolver import MatrixResolverInterface, Renewal
from acme.om.matrix.storage import MatrixStorageInterface, MatrixTenantStorageInterface
from acme.om.matrix.types.matrix import (
    Environment,
    MatrixQuery,
    MatrixStatus,
    MatrixVersion,
    WorkloadClass,
)
from acme.om.matrix.types.record import ModelRef
from acme.om.matrix.types.tenant import MatrixPin
from acme.om.models.prices import ModelPricesInterface
from acme.om.models.types.fill import (
    Eligibility,
    Fill,
    FillSet,
    ModelRole,
    RoleFill,
    SwitchReason,
)
from acme.om.placement.rules import DEFAULT_TIER
from acme.om.placement.storage import PlacementStorageInterface
from acme.om.trust.storage import TrustStorageInterface

log = logging.getLogger(__name__)

DEFAULT_WORKLOAD = "standard"
"""The workload class of a session no product classified."""

Workload = Callable[[AgentSession], WorkloadClass]
"""A product's classes of work: the workload class of a session."""


class MatrixOptions(Platform):
    environment: Environment = "local"  # the environment every question names
    default_tier: str = DEFAULT_TIER  # the plan tier of a tenant no operator gave a share
    reads: int = 1000  # the results, retirements, or choices one read takes at most
    purge_batch: int = 1000  # the pins and choices one purge statement deletes at most


@dataclass(frozen=True)
class _Tenant:
    """What the matrix reads of a tenant for one resolution: the providers
    it holds a live key for, when it is on its own keys, and its own choice
    of fill for each model role, which only such a tenant has."""

    held: frozenset[ProviderName] | None
    chosen: dict[ModelRole, Fill]


class MatrixResolverImpl(MatrixResolverInterface):
    def __init__(
        self,
        matrix: MatrixStorageInterface,
        tenants: MatrixTenantStorageInterface,
        sessions: AgentSessionStorageInterface,
        shares: PlacementStorageInterface,
        accounts: AccountStorageInterface,
        keys: TrustStorageInterface,
        prices: ModelPricesInterface,
        options: MatrixOptions,
        workload: Workload | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._matrix = matrix
        self._tenants = tenants
        self._sessions = sessions
        self._shares = shares
        self._accounts = accounts
        self._keys = keys
        self._prices = prices
        self._options = options
        self._workload = workload or (lambda _: DEFAULT_WORKLOAD)
        self._clock = clock

    def describe(self) -> str:
        return f"model resolver: the matrix, in {self._options.environment}"

    def check(self, fill: Fill) -> None:
        if not self._prices.priced(fill.provider, fill.model):
            raise UnpricedModel(f"{fill.name} has no price row")

    async def resolve(
        self,
        ctx: TenantContext,
        session_id: UUID,
        roles: Sequence[ModelRole],
        eligibility: Eligibility,
    ) -> tuple[RoleFill, ...]:
        version = await self._pinned(ctx, session_id)
        retired = await self.retired()
        ask = await self._asking(ctx, session_id)
        tenant = await self._tenant(ctx)
        return tuple(
            self._answer(version, ask(role), eligibility, retired, tenant)
            for role in sorted(set(roles))
        )

    async def renewal(
        self, ctx: TenantContext, session_id: UUID, head: FillSet, required: Eligibility
    ) -> Renewal | None:
        retired = await self.retired()
        gone = [
            (
                entry.role,
                SwitchReason.RETIRED if ModelRef.of(entry.fill) in retired else SwitchReason.POLICY,
            )
            for entry in head.roles
            if ModelRef.of(entry.fill) in retired or not required.admits(entry.fill.eligibility)
        ]
        if not gone:
            return None
        current = await self._current()
        ask = await self._asking(ctx, session_id)
        tenant = await self._tenant(ctx)
        switches = tuple(
            (role, self._answer(current, ask(role), required, retired, tenant).fill, reason)
            for role, reason in gone
        )
        return current.number, switches

    async def retired(self) -> frozenset[ModelRef]:
        found = await self._matrix.read_retirements(self._options.reads)
        return frozenset(retirement.ref for retirement in found)

    def _answer(
        self,
        version: MatrixVersion,
        query: MatrixQuery,
        eligibility: Eligibility,
        retired: frozenset[ModelRef],
        tenant: _Tenant,
    ) -> RoleFill:
        role = query.role
        if role not in version.roles:
            raise UnresolvedRole(f"matrix version {version.number} serves no model role {role}")
        admits = rules.admitted(eligibility, retired, tenant.held)
        chosen = tenant.chosen.get(role)
        if chosen is not None and not (chosen in rules.serves(version, role) and admits(chosen)):
            chosen = None  # no longer qualified, eligible, or held: the matrix answers
        fills = rules.with_choice(rules.answer(version.rows, query, admits), chosen)
        if not fills and tenant.held is not None:
            # A tenant on its own keys that holds a key for no fill the matrix
            # answers: the matrix's fill alone, whose call parks until the
            # tenant saves its key, never a fallback on a key it lacks.
            unheld = rules.admitted(eligibility, retired, None)
            fills = rules.answer(version.rows, query, unheld)[:1]
        if not fills:
            raise UnresolvedRole(
                f"no fill of matrix version {version.number} the session may run on "
                f"serves the model role {role}"
            )
        for fill in fills:
            self.check(fill)
        return RoleFill(role=role, fill=fills[0], fallbacks=fills[1:])

    async def _pinned(self, ctx: TenantContext, session_id: UUID) -> MatrixVersion:
        """The version the session is pinned to: the one published when its
        fills were first resolved, kept across every later publication."""
        pin = await self._tenants.read_pin(ctx.org_id, session_id)
        if pin is None:
            current = await self._current()
            pin = await self._tenants.write_pin(
                ctx.org_id,
                MatrixPin(
                    id=new_id(),
                    created_at=self._clock(),
                    session_id=session_id,
                    fill_set_version=1,
                    matrix_version=current.number,
                ),
            )
        version = await self._matrix.read_version(pin.matrix_version)
        if version is None:
            raise UnresolvedRole(f"matrix version {pin.matrix_version} is not stored")
        return version

    async def _current(self) -> MatrixVersion:
        current = await self._matrix.read_latest(MatrixStatus.PUBLISHED)
        if current is None:
            raise UnresolvedRole("no version of the matrix is published")
        return current

    async def _asking(
        self, ctx: TenantContext, session_id: UUID
    ) -> Callable[[ModelRole], MatrixQuery]:
        """The question the session asks for each model role."""
        session = await self._sessions.read_session(ctx.org_id, session_id)
        if session is None:
            raise NotFound(f"agent session {session_id} not found")
        share = await self._shares.read_share(ctx.org_id)
        tier = self._options.default_tier if share is None else share.plan_tier
        workload = self._workload(session)

        def ask(role: ModelRole) -> MatrixQuery:
            return MatrixQuery(
                environment=self._options.environment,
                role=role,
                kind=session.kind,
                plan_tier=tier,
                workload=workload,
            )

        return ask

    async def _tenant(self, ctx: TenantContext) -> _Tenant:
        try:
            account = await self._accounts.read_account(ctx.org_id)
        except (ValidationFailed, ValidationError) as unread:
            # Who pays is the call's to refuse; the fills are not narrowed on
            # an account this process cannot read.
            log.error("the billing account of org %s cannot be read: %s", ctx.org_id, unread)
            account = None
        if account is None or account.funding is not FundingMode.OWN_KEY:
            return _Tenant(held=None, chosen={})
        held = frozenset(
            [p for p in ProviderName if await self._keys.read_live_key(ctx.org_id, p) is not None]
        )
        choices = await self._tenants.read_overrides(ctx.org_id, self._options.reads)
        return _Tenant(held=held, chosen={choice.role: choice.fill for choice in choices})
