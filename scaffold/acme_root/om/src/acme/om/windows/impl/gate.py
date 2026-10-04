from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID

from acme.infra.observability import MODEL_SPEND_MICROS, MODEL_TOKENS
from acme.integrations.model_providers.calls import ModelCall
from acme.integrations.model_providers.types import Usage
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.attribution.types.principal import Principal
from acme.om.base import utcnow
from acme.om.budgets import BudgetGateInterface
from acme.om.budgets.pricing import ModelPrice, PricingInterface
from acme.om.budgets.rules import call_exposure, job_exposure, usage_spend
from acme.om.budgets.types.amount import Spend
from acme.om.budgets.types.breach import Refusal
from acme.om.budgets.types.budget import BudgetScope, BudgetScopeKind
from acme.om.budgets.types.hold import (
    Bill,
    Billed,
    BillUnknown,
    HoldRequest,
    NotBilled,
    NotBilledProof,
    Settlement,
)
from acme.om.context import TenantContext
from acme.om.exceptions import BudgetRefused, Unavailable
from acme.om.models.types.fill import Fill, ModelRole
from acme.om.projects.policies import SessionProjectsInterface
from acme.om.windows.gate import CallGateInterface
from acme.om.windows.rules import call_shape

UNPINNED = "none"
"""The matrix version a call counts under when no matrix pinned its
session: a root that wired none, or a session before its first loop."""

PinnedVersion = Callable[[TenantContext, UUID], Awaitable[int | None]]
"""Reads the matrix version a session's fills came from last."""


PlanTierOf = Callable[[TenantContext, UUID], Awaitable[str]]
"""Reads the plan tier a session's tenant is served at: the tier of its
share, one of the few names the operators give, so the set is bounded."""

CallLabels = tuple[str, str]
"""The matrix version and the plan tier a call counts under."""

UNLABELLED: CallLabels = (UNPINNED, UNPINNED)
"""The labels of a call no version and no tier was read for."""


async def version_label(version: PinnedVersion | None, ctx: TenantContext, session_id: UUID) -> str:
    """The label a session's calls count under: its pinned matrix version, a
    published one, so the set is bounded; `none` when nothing pinned it."""
    pinned = None if version is None else await version(ctx, session_id)
    return UNPINNED if pinned is None else str(pinned)


async def call_labels(
    version: PinnedVersion | None,
    tier: PlanTierOf | None,
    ctx: TenantContext,
    session_id: UUID,
) -> CallLabels:
    """The labels a session's calls count under: its pinned matrix version,
    and its tenant's plan tier, `none` where a root wired nothing to read
    it."""
    plan_tier = UNPINNED if tier is None else await tier(ctx, session_id)
    return await version_label(version, ctx, session_id), plan_tier


def count_settled(labels: CallLabels, usage: Usage | None, settlement: Settlement) -> None:
    """A settled model call's tokens, when the provider reported them, and
    the spend its settlement took, under the matrix version its session was
    pinned to and its tenant's plan tier. The cache's share of the prompt is
    `cache_read` against the rest: a fall in it is a cache rebuilt."""
    version, tier = labels
    if usage is not None:
        for kind, tokens in (
            ("input", usage.input),
            ("cache_read", usage.cache_read),
            ("cache_write", usage.cache_write),
            ("output", usage.output + usage.thinking),
        ):
            MODEL_TOKENS.labels(matrix_version=version, plan_tier=tier, kind=kind).inc(tokens)
    if settlement.spent.cost_micros:
        MODEL_SPEND_MICROS.labels(matrix_version=version, plan_tier=tier).inc(
            settlement.spent.cost_micros
        )


class CallGateNullImpl(CallGateInterface):
    """The gate of a root that wired none. It is loud: a compaction spends,
    and a call that skipped the gate would spend outside every budget, so it
    refuses and says why."""

    async def authorize(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spender: Principal,
        role: ModelRole,
        fill: Fill,
        call: ModelCall,
        *,
        credential: str,
    ) -> UUID:
        raise Unavailable("no budget gate is wired, so no compaction is called")

    async def settle(
        self, ctx: TenantContext, hold_id: UUID, usage: Usage | None, *, billed: bool
    ) -> None:
        raise Unavailable("no budget gate is wired, so there is no hold to settle")

    async def authorize_job(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spender: Principal,
        tool: str,
        rate_micros_per_hour: int,
        deadline: datetime,
    ) -> UUID:
        raise Unavailable("no budget gate is wired, so no job that spends is started")

    async def settle_job(
        self, ctx: TenantContext, hold_id: UUID, cost_micros: int | None, *, started: bool
    ) -> None:
        raise Unavailable("no budget gate is wired, so there is no hold to settle")


class CallGateBudgetImpl(CallGateInterface):
    """The budgets' gate behind the narrow face the windows and the loop
    read. A model call's worst case is priced from the one source of prices
    (`windows.rules.call_shape`, `budgets.rules.call_exposure`) and held on
    every scope the call serves: its session, its tree, the person who pays,
    the project `projects` reads of its session, and the tenant. A refusal
    raises `BudgetRefused`, listing every breach, with nothing held. A
    settlement prices the usage the provider reported at the same list
    price; a call the provider never processed releases its hold. Every
    settled call counts its tokens and its spend, under the matrix version
    `version` reads of its session and the plan tier `tier` reads; None
    counts them under `none`. A spending job is held on the same scopes at
    its rate until its deadline (`budgets.rules.job_exposure`), and settles
    at the cost its runner reported, else whole; a job refused before any
    work began releases its hold."""

    def __init__(
        self,
        gate: BudgetGateInterface,
        pricing: PricingInterface,
        sessions: AgentSessionsManagerInterface,
        projects: SessionProjectsInterface,
        *,
        version: PinnedVersion | None = None,
        tier: PlanTierOf | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._gate = gate
        self._pricing = pricing
        self._sessions = sessions
        self._projects = projects
        self._version = version
        self._tier = tier
        self._clock = clock
        self._held: dict[UUID, tuple[ModelPrice | None, CallLabels]] = {}

    async def authorize(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spender: Principal,
        role: ModelRole,
        fill: Fill,
        call: ModelCall,
        *,
        credential: str,
    ) -> UUID:
        # Whose key the call goes out on changes who pays the provider, never
        # what is gated: the same budgets, at the same list price.
        session = await self._sessions.get_session(ctx, session_id)
        project_id = await self._projects.project_of(ctx, session_id)
        labels = await call_labels(self._version, self._tier, ctx, session_id)
        price = self._pricing.price_of(fill.provider.value, fill.model)
        request = HoldRequest(
            spender_id=spender.id,
            scopes=scopes_of(
                ctx.org_id, session_id, session.root_id, spender, project_id=project_id
            ),
            exposure=call_exposure(call_shape(call, fill), price),
            session_id=session_id,
            purpose=role,
        )
        answer = await self._gate.authorize(ctx, request)
        if isinstance(answer, Refusal):
            raise BudgetRefused(answer)
        self._held[answer.id] = (price, labels)
        return answer.id

    async def settle(
        self, ctx: TenantContext, hold_id: UUID, usage: Usage | None, *, billed: bool
    ) -> None:
        price, labels = self._held.pop(hold_id, (None, UNLABELLED))
        bill: Bill
        if not billed:
            bill = NotBilled(proof=NotBilledProof.REFUSED_BEFORE_PROCESSING)
        elif usage is None:
            bill = BillUnknown()
        else:
            bill = Billed(usage=usage_spend(usage, price))
        settlement = await self._gate.settle(ctx, hold_id, bill)
        count_settled(labels, usage if billed else None, settlement)

    async def authorize_job(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spender: Principal,
        tool: str,
        rate_micros_per_hour: int,
        deadline: datetime,
    ) -> UUID:
        session = await self._sessions.get_session(ctx, session_id)
        project_id = await self._projects.project_of(ctx, session_id)
        request = HoldRequest(
            spender_id=spender.id,
            scopes=scopes_of(
                ctx.org_id, session_id, session.root_id, spender, project_id=project_id
            ),
            exposure=job_exposure(rate_micros_per_hour, self._clock(), deadline),
            session_id=session_id,
            purpose=tool,
        )
        answer = await self._gate.authorize(ctx, request)
        if isinstance(answer, Refusal):
            raise BudgetRefused(answer)
        return answer.id

    async def settle_job(
        self, ctx: TenantContext, hold_id: UUID, cost_micros: int | None, *, started: bool
    ) -> None:
        bill: Bill
        if not started:
            bill = NotBilled(proof=NotBilledProof.REFUSED_BEFORE_PROCESSING)
        elif cost_micros is None:
            bill = BillUnknown()
        else:
            bill = Billed(usage=Spend(cost_micros=cost_micros, tokens=0))
        await self._gate.settle(ctx, hold_id, bill)


def scopes_of(
    org_id: UUID,
    session_id: UUID,
    tree_id: UUID,
    spender: Principal,
    *,
    project_id: UUID | None,
) -> tuple[BudgetScope, ...]:
    """The scopes a model call of a session is charged to: the session, the
    tree it draws on, the person who pays, the project the session belongs
    to, by its id, and the tenant. A session of no project is charged to no
    project. A team's scope is the platform's to add."""
    project = (
        ()
        if project_id is None
        else (BudgetScope(kind=BudgetScopeKind.PROJECT, key=str(project_id)),)
    )
    return (
        BudgetScope(kind=BudgetScopeKind.SESSION, key=str(session_id)),
        BudgetScope(kind=BudgetScopeKind.TREE, key=str(tree_id)),
        BudgetScope(kind=BudgetScopeKind.PERSON, key=str(spender.id)),
        *project,
        BudgetScope(kind=BudgetScopeKind.TENANT, key=str(org_id)),
    )
