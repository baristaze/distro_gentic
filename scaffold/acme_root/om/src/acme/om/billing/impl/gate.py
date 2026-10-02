import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError

from acme.infra.observability import MODEL_SPEND_MICROS, MODEL_TOKENS, OUTCOMES
from acme.integrations.model_providers.calls import ModelCall
from acme.integrations.model_providers.types import Usage
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.attribution.types.principal import Principal
from acme.om.base import Platform, new_id, utcnow
from acme.om.billing.gate import MoneyGateInterface
from acme.om.billing.pager import AnomalyPage, OperatorPagerInterface
from acme.om.billing.prices import PriceBookInterface
from acme.om.billing.rules import (
    AnomalyGuard,
    anomaly_park,
    charge_of,
    far_above,
    funding_of,
    lines_of,
    norm_of,
    shortfall_park,
    units_of,
)
from acme.om.billing.storage import AccountStorageInterface, MoneyLedgerStorageInterface
from acme.om.billing.types.account import Account
from acme.om.billing.types.ledger import Approval, FundedHold, PricedAt, Turned
from acme.om.billing.types.plan import PlanCatalog, UnitScale
from acme.om.budgets.rules import call_exposure, settlement_of, usage_spend
from acme.om.budgets.storage import BudgetStorageInterface
from acme.om.budgets.types.breach import Refusal
from acme.om.budgets.types.hold import (
    Bill,
    Billed,
    BillUnknown,
    Hold,
    HoldRequest,
    NotBilled,
    NotBilledProof,
    Settlement,
)
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import (
    BudgetRefused,
    GateParked,
    NotFound,
    SpenderUnknown,
    ValidationFailed,
)
from acme.om.models.types.fill import Fill, ModelRole
from acme.om.windows.gate import CallGateInterface
from acme.om.windows.impl.gate import scopes_of
from acme.om.windows.rules import call_shape

log = logging.getLogger(__name__)


class MoneyGateOptions(Platform):
    max_lines: int = 32  # budgets one call may be charged to, at most
    guard: AnomalyGuard = AnomalyGuard()


class MoneyGateImpl(MoneyGateInterface):
    """The engine's gate with the platform behind it. Who pays is read
    first, and a call nobody can be named to pay for spends nothing. Each
    limit counts in its window as the tenant counts it, the anomaly guard
    asks the session's norm, and the ledger holds the worst case on the
    limits and draws it on the buckets in one transaction."""

    def __init__(
        self,
        budgets: BudgetStorageInterface,
        accounts: AccountStorageInterface,
        ledger: MoneyLedgerStorageInterface,
        pager: OperatorPagerInterface,
        plans: PlanCatalog,
        units: UnitScale,
        options: MoneyGateOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._budgets = budgets
        self._accounts = accounts
        self._ledger = ledger
        self._pager = pager
        self._plans = plans
        self._units = units
        self._options = options
        self._clock = clock

    async def authorize(self, ctx: TenantContext, request: HoldRequest) -> Hold | Refusal:
        answer = await self.authorize_priced(ctx, request, None)
        return answer if isinstance(answer, Refusal) else answer.hold

    async def authorize_priced(
        self,
        ctx: TenantContext,
        request: HoldRequest,
        priced: PricedAt | None,
        *,
        credential: str | None = None,
    ) -> FundedHold | Refusal:
        ctx.require(Permission.WRITE)
        if request.spender_id is None:
            raise SpenderUnknown("the engine cannot tell who pays for this call; nothing is spent")
        now = self._clock()
        account = await self._account(ctx)
        funding = funding_of(account, self._plans, self._units, now, carried=credential)
        assert account is not None
        bound = self._options.max_lines
        found = await self._budgets.read_budgets_for(ctx.org_id, request.scopes, bound + 1)
        if len(found) > bound:
            # A line the gate does not read is spend outside it: refuse.
            raise ValidationFailed(f"more than {bound} budgets bind this call")
        approval = await self._guard(ctx, request)
        hold = FundedHold(
            hold=Hold(
                id=new_id(),
                created_at=now,
                spender_id=request.spender_id,
                session_id=request.session_id,
                purpose=request.purpose,
                exposure=request.exposure,
                own=request.own,
                lines=lines_of(found, account, now),
            ),
            funding=funding,
            units=units_of(request.exposure.cost_micros, funding.micros_per_unit),
            priced=priced,
            approval_id=approval,
        )
        answer = await self._ledger.open_hold(ctx.org_id, hold)
        if isinstance(answer, Turned):
            return self._turned(ctx, request, answer)
        OUTCOMES.labels(subsystem="billing", outcome="held").inc()
        return answer

    async def settle(self, ctx: TenantContext, hold_id: UUID, bill: Bill) -> Settlement:
        ctx.require(Permission.WRITE)
        hold = await self.read_hold(ctx, hold_id)
        now = self._clock()
        settlement = settlement_of(hold.hold, bill, new_id(), now)
        charge = charge_of(hold, settlement, new_id(), now)
        stored, _ = await self._ledger.close_hold(ctx.org_id, settlement, charge)
        if stored.id != settlement.id:
            return stored  # closed already: the first settlement counts
        if stored.overshoot is not None:
            # Counted and charged in full, never absorbed.
            log.error(
                "hold %s in org %s settled past its worst case by %s micros and %d tokens",
                hold.id,
                ctx.org_id,
                stored.overshoot.cost_micros,
                stored.overshoot.tokens,
            )
            OUTCOMES.labels(subsystem="billing", outcome="overshoot").inc()
        OUTCOMES.labels(subsystem="billing", outcome=f"settled_{stored.bill.kind}").inc()
        if hold.priced is not None and stored.spent.cost_micros:
            # A model call's spend, once per hold, by the plan the gate read.
            MODEL_SPEND_MICROS.labels(plan=hold.funding.plan.id).inc(stored.spent.cost_micros)
        return stored

    async def read_hold(self, ctx: TenantContext, hold_id: UUID) -> FundedHold:
        hold = await self._ledger.read_hold(ctx.org_id, hold_id)
        if hold is None:
            raise NotFound(f"hold {hold_id} not found")
        return hold

    async def _account(self, ctx: TenantContext) -> Account | None:
        """The tenant's account. One this process cannot read is no answer to
        who pays: nothing is spent, and nothing falls back to the platform's
        key."""
        try:
            return await self._accounts.read_account(ctx.org_id)
        except (ValidationFailed, ValidationError) as unread:
            log.error("the billing account of org %s cannot be read: %s", ctx.org_id, unread)
            raise SpenderUnknown(
                "the tenant's billing account cannot be read; nothing is spent"
            ) from unread

    async def _guard(self, ctx: TenantContext, request: HoldRequest) -> UUID | None:
        """The anomaly guard, before anything is held: a call whose expected
        cost is far above its session's norm pages the operator and parks
        for a person, unless a person approved it. Returns the approval it
        rides on, if any."""
        if request.session_id is None:
            return None
        guard = self._options.guard
        entries = await self._ledger.read_entries(
            ctx.org_id, session_id=request.session_id, limit=guard.recent + 1
        )
        recent: list[int] = []
        used: set[UUID] = set()
        approval: Approval | None = None
        for entry in entries:  # newest first
            if isinstance(entry, Approval):
                approval = approval or entry
            elif isinstance(entry, FundedHold):
                if entry.approval_id is not None:
                    used.add(entry.approval_id)
                    continue
                cost_of = entry.hold.exposure.cost_micros
                if cost_of is not None and len(recent) < guard.recent:
                    recent.append(cost_of)
        cost = request.exposure.cost_micros
        if not far_above(cost, recent, guard):
            return None
        assert cost is not None
        if approval is not None and approval.id not in used and cost <= approval.up_to_micros:
            return approval.id
        page = AnomalyPage(
            org_id=ctx.org_id,
            session_id=request.session_id,
            expected_micros=cost,
            norm_micros=norm_of(recent),
        )
        await self._pager.page(page)
        OUTCOMES.labels(subsystem="billing", outcome="anomaly").inc()
        raise GateParked(
            anomaly_park(),
            f"the call's expected cost, {cost} micros, is far above its session's norm",
        )

    def _turned(self, ctx: TenantContext, request: HoldRequest, turned: Turned) -> Refusal:
        """A limit's breaches are the engine's refusal, which parks on the
        budget. Units no bucket covers park on the budget too, as a spend
        limit, naming the funds; the limits come first, since a top-up
        clears none of them."""
        log.info("turned %s away in org %s", request.purpose, ctx.org_id)
        OUTCOMES.labels(subsystem="billing", outcome="refused").inc()
        if turned.refusal is not None:
            return turned.refusal
        assert turned.shortfall is not None
        shortfall = turned.shortfall
        held = (
            " until other calls' open holds settle" if shortfall.short <= shortfall.reserved else ""
        )
        raise GateParked(
            shortfall_park(shortfall, self._clock()),
            f"no bucket covers {shortfall.short} units of the call{held}",
        )


class MoneyCallGateImpl(CallGateInterface):
    """The face the windows and the loop read, over the money gate. A model
    call's worst case is priced from the price table in force and held with
    the row it was read from; its usage is billed from that same row, after
    the next version is read and in another process too."""

    def __init__(
        self,
        gate: MoneyGateInterface,
        prices: PriceBookInterface,
        sessions: AgentSessionsManagerInterface,
    ) -> None:
        self._gate = gate
        self._prices = prices
        self._sessions = sessions

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
        session = await self._sessions.get_session(ctx, session_id)
        priced = PricedAt(
            version=self._prices.version, provider=fill.provider.value, model=fill.model
        )
        price = self._prices.price_at(priced.version, priced.provider, priced.model)
        request = HoldRequest(
            spender_id=spender.id,
            scopes=scopes_of(ctx.org_id, session_id, session.root_id, spender),
            exposure=call_exposure(call_shape(call, fill), price),
            session_id=session_id,
            purpose=role,
        )
        answer = await self._gate.authorize_priced(ctx, request, priced, credential=credential)
        if isinstance(answer, Refusal):
            raise BudgetRefused(answer)
        return answer.id

    async def settle(
        self, ctx: TenantContext, hold_id: UUID, usage: Usage | None, *, billed: bool
    ) -> None:
        bill: Bill
        if not billed:
            bill = NotBilled(proof=NotBilledProof.REFUSED_BEFORE_PROCESSING)
        elif usage is None:
            bill = BillUnknown()
        else:
            hold = await self._gate.read_hold(ctx, hold_id)
            price = None
            if hold.priced is not None:
                version, provider, model = (
                    hold.priced.version,
                    hold.priced.provider,
                    hold.priced.model,
                )
                price = self._prices.price_at(version, provider, model)
            bill = Billed(usage=usage_spend(usage, price))
            # The cache's share of the prompt, by the plan the gate read: a
            # fall in `cache_read` against the rest is a cache rebuilt.
            plan = hold.funding.plan.id
            for kind, tokens in (
                ("input", usage.input),
                ("cache_read", usage.cache_read),
                ("cache_write", usage.cache_write),
                ("output", usage.output + usage.thinking),
            ):
                MODEL_TOKENS.labels(plan=plan, kind=kind).inc(tokens)
        await self._gate.settle(ctx, hold_id, bill)
