"""Money behind the engine's gate, over the memory storage: a cap and a bill
read one row of one versioned price table, and every hold, settlement, and
charge posts to the one ledger; a change of time zone never makes a second
day's budget inside one real day; a credit counts only once its signed
confirmation checks out, and a top-up raises no limit; a tenant nobody can
name to pay spends nothing; a rate limit and a spend limit park apart and
are told apart; and a call far above its session's norm parks for a person
and pages the operator."""

from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from uuid import UUID

import pytest

from acme.integrations.exceptions import DeliveryRefused
from acme.integrations.model_providers.calls import ModelCall
from acme.integrations.model_providers.scripted import ScriptedFailure
from acme.integrations.model_providers.types import ErrorKind, ProviderName, Usage
from acme.integrations.payments.twin import PaymentProviderTwinImpl
from acme.om.agent_billing.impl.gate import MoneyCallGateImpl, MoneyGateOptions
from acme.om.agent_billing.impl.prices import PriceBookTableImpl
from acme.om.agent_billing.impl.sweep import HoldSweepImpl, HoldSweepOptions
from acme.om.agent_billing.prices import PriceBookInterface
from acme.om.agent_billing.rules import (
    ANOMALY_UNLOCK,
    FUNDS_UNLOCK,
    HELD_UNLOCK,
    PRICE_RETRY,
    PRICE_UNLOCK,
    AnomalyGuard,
    LimitKind,
    credential_of,
    notice_of,
    units_of,
    zoned_window,
)
from acme.om.agent_billing.sweep import ProviderBillsUnknownImpl
from acme.om.agent_billing.types.spend_account import FundingMode, SpendAccount, ZoneChange
from acme.om.agent_billing.types.spend_ledger import Charge, EntryKind, FundedHold, PricedAt
from acme.om.agent_billing.types.unit_plan import SPEND_UNITS, UnitPlan, UnitPlanCatalog
from acme.om.agent_projects.impl.policies import SessionAgentProjectsBoundImpl
from acme.om.agent_sessions.types.agent_session import AgentSessionStatus
from acme.om.agent_steps.types.agent_step import AgentStepType
from acme.om.agent_steps.types.header import LoopOutcome, ParkReason, ToolRequestHeader
from acme.om.agents.loop_rules import SPENDER_UNLOCK
from acme.om.agents.types.run import RunEnd
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import new_id
from acme.om.context import (
    AppContext,
    AppType,
    OperatorPermission,
    OperatorRole,
    RequestContext,
    TenantContext,
)
from acme.om.exceptions import GateParked, NotAuthorized, SpendBudgetRefused, SpenderUnknown
from acme.om.language_models.types.fill import MAIN, Eligibility
from acme.om.spend_budgets.impl.pricing import LIST_PRICES
from acme.om.spend_budgets.pricing import ModelPrice, PriceRow, PriceTable, Rates
from acme.om.spend_budgets.rules import call_exposure, usage_spend
from acme.om.spend_budgets.types.amount import Spend
from acme.om.spend_budgets.types.spend_breach import Refusal
from acme.om.spend_budgets.types.spend_budget import (
    SpendBudgetScope,
    SpendBudgetScopeKind,
    WindowKind,
)
from acme.om.spend_budgets.types.spend_hold import Billed, SpendHoldRequest, SpendSettlement
from acme.om.spend_budgets.types.usage import CallSite
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tools.types.call import JobCompletion
from acme.om.tools.types.policy import Decision, ToolPolicyLayer, ToolPolicyRule
from acme.om.tools.types.tool import Effect, ToolClass
from acme.om.windows.gate import CallGateInterface
from acme.om.windows.impl.gate import CallGateSpendBudgetImpl
from acme.om.windows.rules import call_shape

from contracts.agent_project_storage import in_agent_project
from contracts.benchmark_storage import operator
from contracts.loops import ASSISTANT, BUILDER, DELIVERY, Lookup, call, reply, said, use
from contracts.money import Money, money_over
from contracts.spend_budget_storage import make_spend_budget

PREPAID = UnitPlanCatalog(
    unit_plans=(UnitPlan(id="prepaid", version=1, included_units=0, unit_price_micros=1_000),)
)
"""A unit plan that includes nothing: every unit is paid from a money bucket."""

KIRITIMATI = "Pacific/Kiritimati"  # UTC+14, no daylight saving
BAKER = "Etc/GMT+12"  # UTC-12, no daylight saving


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def spender(ctx: TenantContext) -> Principal:
    return Principal(kind=PrincipalKind.PERSON, id=ctx.user_id)


def tenant_request(
    ctx: TenantContext, cost_micros: int, *, agent_session_id: UUID | None = None
) -> SpendHoldRequest:
    """A call charged to the tenant's scope, at a worst case of `cost_micros`."""
    return SpendHoldRequest(
        spender_id=ctx.user_id,
        scopes=(SpendBudgetScope(kind=SpendBudgetScopeKind.TENANT, key=str(ctx.org_id)),),
        exposure=Spend(cost_micros=cost_micros, tokens=0),
        agent_session_id=agent_session_id,
        purpose=MAIN,
    )


async def spend(
    money: Money, cost_micros: int, *, agent_session_id: UUID | None = None
) -> FundedHold:
    """A call that fits, held and settled at its whole worst case."""
    owner = money.loop.owner
    hold = await money.gate.authorize_priced(
        owner, tenant_request(owner, cost_micros, agent_session_id=agent_session_id), None
    )
    assert isinstance(hold, FundedHold), hold
    await money.gate.settle(owner, hold.id, Billed(usage=hold.hold.exposure))
    return hold


async def entries_of(money: Money, spend_hold_id: UUID) -> dict[str, object]:
    found = await money.ledger.read_entries(
        money.loop.owner.org_id, spend_hold_id=spend_hold_id, limit=10
    )
    return {type(entry).__name__: entry for entry in found}


# A cap and a bill read the same price, and one ledger holds them.


def a_later_reading(model: str) -> PriceTable:
    """The next reading of the list: `model` at twice its rates."""
    rows = []
    for row in LIST_PRICES.rows:
        if row.model == model:
            rates = row.price.rates
            doubled = Rates(
                input=rates.input * 2,
                cache_write=rates.cache_write * 2,
                cache_read=rates.cache_read * 2,
                output=rates.output * 2,
                cache_write_long=None
                if rates.cache_write_long is None
                else rates.cache_write_long * 2,
            )
            row = PriceRow(
                provider=row.provider,
                model=row.model,
                price=ModelPrice(rates=doubled, tool_fees=row.price.tool_fees),
                as_of=row.as_of + timedelta(days=30),
            )
        rows.append(row)
    return PriceTable(version="2026-11-01", rows=tuple(rows))


async def test_a_cap_and_a_bill_read_the_same_row_of_one_versioned_table(tmp_path: Path) -> None:
    """The cap is read from the table in force, and the bill from the row the
    cap was read from, even once the next reading is in force, in a gate
    that never saw the first."""
    money = money_over(tmp_path)
    await money.open(unit_plan="team")
    owner = money.loop.owner
    agent_session_id = await money.loop.start()
    fills = await money.loop.managers.language_models.resolve_fill_set(
        owner, agent_session_id, ASSISTANT.roles, Eligibility()
    )
    fill = fills.fill_for(MAIN)
    assert fill is not None
    call = ModelCall(model=fill.model, messages=(), max_output_tokens=4_000)
    first = money.prices.price_at(LIST_PRICES.version, fill.provider.value, fill.model)
    assert first is not None

    spend_hold_id = await money.calls.authorize(
        owner, agent_session_id, spender(owner), MAIN, fill, call, credential="platform"
    )

    hold = await money.gate.read_hold(owner, spend_hold_id)
    assert hold.priced == PricedAt(
        version=LIST_PRICES.version, provider=fill.provider.value, model=fill.model
    )
    assert hold.hold.exposure == call_exposure(call_shape(call, fill), first), (
        "the cap read the row"
    )

    later = a_later_reading(fill.model)
    book = PriceBookTableImpl((LIST_PRICES, later))
    assert book.version == later.version
    next_process = MoneyCallGateImpl(
        money.gate,
        book,
        money.loop.managers.agent_sessions,
        money.loop.managers.spend_budgets,
        SessionAgentProjectsBoundImpl(money.loop.storage.get_agent_project_storage()),
    )
    usage = Usage(input=120_000, output=3_000)
    # Another process never held the call, and its site names no labels, so
    # the bill lands and no usage record does.
    site = CallSite(loop_id=new_id(), agent_step_id=new_id(), latency_ms=0)
    await next_process.settle(owner, spend_hold_id, usage, billed=True, site=site)

    found = await entries_of(money, spend_hold_id)
    settlement, charge = found["SpendSettlement"], found["Charge"]
    assert isinstance(settlement, SpendSettlement) and isinstance(charge, Charge)
    billed = usage_spend(usage, first)
    assert settlement.spent == billed, "the bill read the row the cap read"
    assert charge.price_version == LIST_PRICES.version
    assert charge.units == units_of(billed.cost_micros, SPEND_UNITS.micros_per_unit)
    newer = usage_spend(usage, book.price_at(later.version, fill.provider.value, fill.model))
    assert charge.units != units_of(newer.cost_micros, SPEND_UNITS.micros_per_unit), (
        "the rows differ"
    )


async def test_a_hold_a_settlement_and_a_charge_post_to_the_one_ledger(tmp_path: Path) -> None:
    """A loop's model call holds, settles, and is charged in the one ledger,
    and the engine's own ledger holds none of it."""
    money = money_over(tmp_path)
    await money.open(unit_plan="team")
    agent_session_id = await money.loop.start()
    await money.loop.say(agent_session_id, "What is the total?")
    money.loop.anthropic.add(reply(said("The total is 12.")))

    ran = await money.loop.loops.run(money.loop.owner, agent_session_id)

    assert ran.end is RunEnd.ENDED, ran
    org = money.loop.owner.org_id
    (hold,) = await money.ledger.read_entries(org, kind=EntryKind.HOLD, limit=10)
    assert isinstance(hold, FundedHold) and hold.agent_session_id == agent_session_id
    found = await entries_of(money, hold.id)
    assert sorted(found) == ["Charge", "FundedHold", "SpendSettlement"]
    charge = found["Charge"]
    assert isinstance(charge, Charge) and charge.units > 0 and charge.amount_micros == 0, (
        "the unit plan's included units paid for it"
    )
    engine_ledger = money.loop.storage.get_ledger_storage()
    assert await engine_ledger.read_hold(org, hold.id) is None, "no second ledger"


async def test_an_operator_reads_the_ledger_of_the_tenant_it_names_under_its_read(
    tmp_path: Path,
) -> None:
    """The operators' read of a tenant's ledger: its entries, of one kind, one
    hold, or one session when named, and whether the read was cut at its
    limit; another tenant named reads none of them, and an operator who holds
    no read reads nothing."""
    money = money_over(tmp_path)
    await money.open(unit_plan="team")
    agent_session_id = await money.loop.start()
    await money.loop.say(agent_session_id, "What is the total?")
    money.loop.anthropic.add(reply(said("The total is 12.")))
    assert (await money.loop.loops.run(money.loop.owner, agent_session_id)).end is RunEnd.ENDED
    org = money.loop.owner.org_id
    reader = operator(OperatorRole.READ)

    page = await money.agent_billing.get_entries(reader, org, limit=50)
    assert not page.has_more
    assert sorted(type(entry).__name__ for entry in page.items) == [
        "Charge",
        "FundedHold",
        "SpendSettlement",
    ]
    (charge,) = (
        await money.agent_billing.get_entries(reader, org, kind=EntryKind.CHARGE, limit=50)
    ).items
    assert isinstance(charge, Charge)
    (hold,) = (
        await money.agent_billing.get_entries(
            reader, org, agent_session_id=agent_session_id, limit=50
        )
    ).items
    assert isinstance(hold, FundedHold)
    of_hold = await money.agent_billing.get_entries(reader, org, spend_hold_id=hold.id, limit=50)
    assert sorted(type(entry).__name__ for entry in of_hold.items) == [
        "Charge",
        "FundedHold",
        "SpendSettlement",
    ]
    cut = await money.agent_billing.get_entries(reader, org, limit=2)
    assert len(cut.items) == 2 and cut.has_more
    elsewhere = await money.agent_billing.get_entries(reader, new_id(), limit=50)
    assert elsewhere.items == () and not elsewhere.has_more
    minting = reader.model_copy(update={"permissions": frozenset({OperatorPermission.MINT})})
    with pytest.raises(NotAuthorized):
        await money.agent_billing.get_entries(minting, org, limit=50)


async def test_the_buckets_are_drawn_in_their_fixed_order_and_prepaid_differs_only_in_which_pays(
    tmp_path: Path,
) -> None:
    """Included units first, then granted units, then credits; a call no
    bucket covers parks on the budget, naming the funds."""
    unit_plans = UnitPlanCatalog(
        unit_plans=(UnitPlan(id="small", version=1, included_units=3, unit_price_micros=1_000),)
    )
    money = money_over(tmp_path, unit_plans=unit_plans)
    await money.open(unit_plan="small")
    owner = money.loop.owner
    await money.top_up(2_000)

    hold = await spend(money, 5_000)  # 5 units: 3 included, then 2 from credits

    assert hold.draw.included == 3 and hold.draw.granted == 0 and hold.draw.credits == 2_000
    with pytest.raises(GateParked) as parked:
        await money.gate.authorize(owner, tenant_request(owner, 1_000))
    assert parked.value.park.reason is ParkReason.SPEND_BUDGET
    assert parked.value.park.unlock == FUNDS_UNLOCK
    assert parked.value.park.retry_at is not None, "the next billing period refills the unit plan"


async def test_a_call_short_only_of_what_open_holds_reserve_tries_again_soon(
    tmp_path: Path,
) -> None:
    """Ten included units, eight held by a call still open: a call for five
    parks on the budget and tries again within seconds, not at the period's
    end, and fits once the open call settles."""
    unit_plans = UnitPlanCatalog(
        unit_plans=(UnitPlan(id="ten", version=1, included_units=10, unit_price_micros=1_000),)
    )
    money = money_over(tmp_path, unit_plans=unit_plans)
    await money.open(unit_plan="ten")
    owner = money.loop.owner
    first = await money.gate.authorize_priced(owner, tenant_request(owner, 8_000), None)
    assert isinstance(first, FundedHold) and first.draw.included == 8

    with pytest.raises(GateParked) as parked:
        await money.gate.authorize_priced(owner, tenant_request(owner, 5_000), None)

    park = parked.value.park
    assert park.reason is ParkReason.SPEND_BUDGET and park.unlock == HELD_UNLOCK
    assert park.retry_at is not None
    assert park.retry_at - money.loop.clock() <= timedelta(seconds=30), (
        "soon, never the period's end"
    )
    assert notice_of(park).limit is LimitKind.SPEND
    await money.gate.settle(owner, first.id, Billed(usage=Spend(cost_micros=3_000, tokens=0)))
    second = await money.gate.authorize_priced(owner, tenant_request(owner, 5_000), None)
    assert isinstance(second, FundedHold) and second.draw.included == 5


# An agent project's budget binds its sessions.


@pytest.mark.parametrize("gate", ["money", "engine"])
async def test_an_agent_projects_budget_refuses_a_call_its_tenants_has_room_for(
    gate: str, tmp_path: Path
) -> None:
    """The call is charged to the agent project its session belongs to, as the
    agent projects answer it: past the agent project's budget it is refused, with the
    agent project's line its one breach, while the tenant's budget has room. A
    session of no agent project is charged to none, and the same call is held."""
    money = money_over(tmp_path)
    await money.open(unit_plan="team")
    loop, owner = money.loop, money.loop.owner
    calls: CallGateInterface = money.calls
    if gate == "engine":
        calls = CallGateSpendBudgetImpl(
            loop.managers.spend_budget_gate,
            loop.managers.pricing,
            loop.managers.agent_sessions,
            loop.managers.spend_budgets,
            SessionAgentProjectsBoundImpl(loop.storage.get_agent_project_storage()),
        )
    ours, loose = await loop.start(), await loop.start()
    agent_project = await in_agent_project(
        loop.storage.get_agent_project_storage(), owner.org_id, ours
    )
    for kind, key, cap in (
        (SpendBudgetScopeKind.TENANT, str(owner.org_id), 1_000_000_000),
        (SpendBudgetScopeKind.AGENT_PROJECT, str(agent_project), 1),
    ):
        await loop.managers.spend_budgets.create_spend_budget(
            owner, make_spend_budget(kind, key, cost_micros=cap)
        )
    fills = await loop.managers.language_models.resolve_fill_set(owner, ours, ASSISTANT.roles, Eligibility())
    fill = fills.fill_for(MAIN)
    assert fill is not None
    call = ModelCall(model=fill.model, messages=(), max_output_tokens=4_000)

    with pytest.raises(SpendBudgetRefused) as refused:
        await calls.authorize(owner, ours, spender(owner), MAIN, fill, call, credential="platform")
    (breach,) = refused.value.refusal.breaches
    assert breach.scope == SpendBudgetScope(
        kind=SpendBudgetScopeKind.AGENT_PROJECT, key=str(agent_project)
    )

    held = await calls.authorize(
        owner, loose, spender(owner), MAIN, fill, call, credential="platform"
    )
    await calls.settle(owner, held, None, billed=False, site=None)


# A spending job passes the same gate.


@pytest.mark.parametrize("gate", ["money", "engine"])
async def test_an_agent_projects_budget_refuses_a_job_its_tenants_has_room_for(
    gate: str, tmp_path: Path
) -> None:
    """A job that spends is held on the scopes a model call is: past its
    agent project's budget it is refused, with the agent project's line its one breach;
    a session of no agent project is held, and a job refused before it began
    releases its hold whole."""
    money = money_over(tmp_path)
    await money.open(unit_plan="team")
    loop, owner = money.loop, money.loop.owner
    calls: CallGateInterface = money.calls
    if gate == "engine":
        calls = CallGateSpendBudgetImpl(
            loop.managers.spend_budget_gate,
            loop.managers.pricing,
            loop.managers.agent_sessions,
            loop.managers.spend_budgets,
            SessionAgentProjectsBoundImpl(loop.storage.get_agent_project_storage()),
            clock=loop.clock,
        )
    ours, loose = await loop.start(), await loop.start()
    agent_project = await in_agent_project(
        loop.storage.get_agent_project_storage(), owner.org_id, ours
    )
    for kind, key, cap in (
        (SpendBudgetScopeKind.TENANT, str(owner.org_id), 1_000_000_000),
        (SpendBudgetScopeKind.AGENT_PROJECT, str(agent_project), 1),
    ):
        await loop.managers.spend_budgets.create_spend_budget(
            owner, make_spend_budget(kind, key, cost_micros=cap)
        )
    deadline = loop.clock() + timedelta(hours=2)

    with pytest.raises(SpendBudgetRefused) as refused:
        await calls.authorize_job(owner, ours, spender(owner), "compute", 3_600_000, deadline)
    (breach,) = refused.value.refusal.breaches
    assert breach.scope == SpendBudgetScope(
        kind=SpendBudgetScopeKind.AGENT_PROJECT, key=str(agent_project)
    )

    held = await calls.authorize_job(owner, loose, spender(owner), "compute", 3_600_000, deadline)
    await calls.settle_job(owner, held, None, started=False)
    if gate == "money":
        settlement = (await entries_of(money, held))["SpendSettlement"]
        assert isinstance(settlement, SpendSettlement) and settlement.spent.cost_micros == 0


async def test_a_spending_job_is_held_settled_and_charged_in_the_one_ledger(
    tmp_path: Path,
) -> None:
    """A loop's spending job is held in the one ledger at its rate until its
    deadline, and its completion settles and charges it at the cost it
    reported."""
    money = money_over(tmp_path, kinds=(ASSISTANT, DELIVERY, BUILDER))
    await money.open(unit_plan="team")
    loop, owner = money.loop, money.loop.owner
    agent_session_id = await loop.start("builder")
    await loop.say(agent_session_id, "Start it.")
    loop.anthropic.add(reply(call("compute", q="everything")), reply(said("It is done.")))

    parked = await loop.loops.run(owner, agent_session_id)

    assert parked.park is not None and parked.park.job is not None
    spend_hold_id = parked.park.job.spend_hold_id
    assert spend_hold_id is not None
    hold = await money.gate.read_hold(owner, spend_hold_id)
    assert hold.hold.purpose == "compute" and hold.priced is None
    assert hold.hold.exposure.cost_micros is not None
    assert hold.hold.exposure.cost_micros >= 7_200_000, "its rate until its deadline"
    request = next(
        s for s in await loop.history(agent_session_id) if s.type is AgentStepType.TOOL_REQUEST
    )
    await loop.loops.complete_job(
        owner,
        agent_session_id,
        JobCompletion(key=request.id, handle="compute-1", text="done", cost_micros=1_234),
    )
    done = await loop.loops.run(owner, agent_session_id)

    assert done.outcome is LoopOutcome.SUCCEEDED
    found = await entries_of(money, spend_hold_id)
    assert sorted(found) == ["Charge", "FundedHold", "SpendSettlement"]
    settlement = found["SpendSettlement"]
    assert isinstance(settlement, SpendSettlement)
    assert settlement.spent.cost_micros == 1_234, "at the cost it reported"


@pytest.mark.parametrize("refusal", ["funds", "payer"])
async def test_a_spending_job_the_money_gate_parks_starts_nothing_and_holds_nothing(
    refusal: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A job no bucket covers parks on the budget, and one nobody can be
    named to pay for parks for a person, as a model call does: the job
    never starts, and the ledger holds nothing for it."""
    unit_plans = UnitPlanCatalog(
        unit_plans=(UnitPlan(id="small", version=1, included_units=5_000, unit_price_micros=1_000),)
    )
    money = money_over(tmp_path, unit_plans=unit_plans, kinds=(ASSISTANT, DELIVERY, BUILDER))
    await money.open(unit_plan="small")
    loop, owner = money.loop, money.loop.owner
    if refusal == "payer":

        async def nobody(*args: object) -> UUID:
            raise SpenderUnknown("the job does not carry the tenant's own key")

        monkeypatch.setattr(money.calls, "authorize_job", nobody)
    agent_session_id = await loop.start("builder")
    await loop.say(agent_session_id, "Start it.")
    loop.anthropic.add(reply(call("compute", q="everything")))

    parked = await loop.loops.run(owner, agent_session_id)

    assert parked.end is RunEnd.PARKED and parked.park is not None
    if refusal == "funds":
        assert parked.park.reason is ParkReason.SPEND_BUDGET
        assert parked.park.unlock in (FUNDS_UNLOCK, HELD_UNLOCK)
    else:
        assert parked.park.reason is ParkReason.PERSON and parked.park.unlock == SPENDER_UNLOCK
    assert loop.jobs["compute"].started == {}, "no job started"
    holds = await money.ledger.read_entries(owner.org_id, kind=EntryKind.HOLD, limit=10)
    assert [h for h in holds if isinstance(h, FundedHold) and h.hold.purpose == "compute"] == []


class OneTenant(TenancyManagerInterface):
    """The one question the hold sweep asks of tenancy, answered with the
    case's owner; any other method fails loudly as unimplemented."""

    def __init__(self, owner: TenantContext) -> None:
        self._owner = owner

    async def service_context(
        self, rctx: RequestContext, org_id: UUID, user_id: UUID
    ) -> TenantContext:
        return self._owner


OneTenant.__abstractmethods__ = frozenset()


async def test_a_jobs_hold_lives_to_its_deadline_and_settles_at_its_reported_cost(
    tmp_path: Path,
) -> None:
    """A job still working past the sweep's hour keeps its hold: the hold
    falls due at the job's deadline, and the sweep leaves it until an hour
    past that. Its completion settles it at the cost it reported."""
    money = money_over(tmp_path, kinds=(ASSISTANT, DELIVERY, BUILDER))
    await money.open(unit_plan="team")
    loop, owner = money.loop, money.loop.owner
    agent_session_id = await loop.start("builder")
    await loop.say(agent_session_id, "Start it.")
    loop.anthropic.add(reply(call("compute", q="everything")), reply(said("It is done.")))
    parked = await loop.loops.run(owner, agent_session_id)
    assert parked.park is not None and parked.park.job is not None
    spend_hold_id = parked.park.job.spend_hold_id
    assert spend_hold_id is not None
    held = await money.gate.read_hold(owner, spend_hold_id)
    assert held.deadline == loop.clock() + timedelta(hours=2), "the job's deadline"
    sweep = HoldSweepImpl(
        money.ledger,
        money.gate,
        OneTenant(owner),  # pyright: ignore[reportAbstractUsage] (a partial double)
        ProviderBillsUnknownImpl(),
        HoldSweepOptions(),
        clock=loop.clock,
    )
    rctx = RequestContext(request_id=new_id(), app=AppContext(type=AppType.PORTAL, version="p@t"))

    loop.clock.now += timedelta(minutes=90)
    await sweep.settle_open(rctx)

    assert "SpendSettlement" not in await entries_of(money, spend_hold_id), "the job still works"
    loop.clock.now += timedelta(minutes=10)
    request = next(
        s for s in await loop.history(agent_session_id) if s.type is AgentStepType.TOOL_REQUEST
    )
    await loop.loops.complete_job(
        owner,
        agent_session_id,
        JobCompletion(key=request.id, handle="compute-1", text="done", cost_micros=1_234),
    )
    done = await loop.loops.run(owner, agent_session_id)

    assert done.outcome is LoopOutcome.SUCCEEDED
    settlement = (await entries_of(money, spend_hold_id))["SpendSettlement"]
    assert isinstance(settlement, SpendSettlement)
    assert settlement.bill.kind == "billed" and settlement.spent.cost_micros == 1_234


async def test_a_job_no_run_settles_is_swept_whole_an_hour_past_its_deadline(
    tmp_path: Path,
) -> None:
    """A job's hold that nothing settles is the sweep's once its deadline is
    an hour past, and counts whole, as a lost model call's does."""
    money = money_over(tmp_path, kinds=(ASSISTANT, DELIVERY, BUILDER))
    await money.open(unit_plan="team")
    loop, owner = money.loop, money.loop.owner
    agent_session_id = await loop.start("builder")
    await loop.say(agent_session_id, "Start it.")
    loop.anthropic.add(reply(call("compute", q="everything")))
    parked = await loop.loops.run(owner, agent_session_id)
    assert parked.park is not None and parked.park.job is not None
    spend_hold_id = parked.park.job.spend_hold_id
    assert spend_hold_id is not None
    sweep = HoldSweepImpl(
        money.ledger,
        money.gate,
        OneTenant(owner),  # pyright: ignore[reportAbstractUsage] (a partial double)
        ProviderBillsUnknownImpl(),
        HoldSweepOptions(),
        clock=loop.clock,
    )
    rctx = RequestContext(request_id=new_id(), app=AppContext(type=AppType.PORTAL, version="p@t"))

    loop.clock.now += timedelta(hours=3, minutes=1)
    assert await sweep.settle_open(rctx) == 1

    held = await money.gate.read_hold(owner, spend_hold_id)
    settlement = (await entries_of(money, spend_hold_id))["SpendSettlement"]
    assert isinstance(settlement, SpendSettlement) and settlement.bill.kind == "unknown"
    assert settlement.spent.cost_micros == held.hold.exposure.cost_micros


async def test_a_run_that_recovers_a_jobs_call_starts_it_once_under_one_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run lost after it wrote a spending job's request, before it held
    anything, leaves the call open. The run that recovers the call holds and
    starts the job once, and parks on that job."""
    money = money_over(tmp_path, kinds=(ASSISTANT, DELIVERY, BUILDER))
    await money.open(unit_plan="team")
    loop, owner = money.loop, money.loop.owner
    agent_session_id = await loop.start("builder")
    await loop.say(agent_session_id, "Start it.")
    loop.anthropic.add(reply(call("compute", q="everything")), reply(said("It is done.")))
    real = money.calls.authorize_job
    lost: list[bool] = []

    async def lost_once(*args: object) -> UUID:
        if not lost:
            lost.append(True)
            raise RuntimeError("the run is lost here")
        return await real(*args)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(money.calls, "authorize_job", lost_once)
    with pytest.raises(RuntimeError):
        await loop.loops.run(owner, agent_session_id)

    parked = await loop.loops.run(owner, agent_session_id)

    assert parked.park is not None and parked.park.reason is ParkReason.JOB
    assert parked.park.job is not None
    holds = await money.ledger.read_entries(owner.org_id, kind=EntryKind.HOLD, limit=10)
    jobs = [h.id for h in holds if isinstance(h, FundedHold) and h.hold.purpose == "compute"]
    assert jobs == [parked.park.job.spend_hold_id], "one job, one hold"
    assert len(loop.jobs["compute"].deadlines) == 1, "started once"


async def test_a_recovered_job_parks_the_loop_once_every_other_lost_call_is_settled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lost run passed over a spending job that waited for approval, ran a
    later unsafe call, and was lost before that call's answer. The run that
    recovers starts the job under one hold, settles the unsafe call by its
    effect, and only then parks on the job: the unsafe call runs once."""
    poke = Lookup("poke", effect=Effect.UNSAFE, authorization_class=ToolClass.WRITE)
    asks = ToolPolicyLayer(
        rules=(
            ToolPolicyRule(authorization_class=ToolClass.READ, decision=Decision.ALLOW),
            ToolPolicyRule(authorization_class=ToolClass.WRITE, decision=Decision.ALLOW),
            ToolPolicyRule(tool="compute", decision=Decision.APPROVE),
        )
    )
    kind = BUILDER.model_copy(
        update={"name": "asker", "tools": ("compute", "poke"), "policy": asks}
    )
    money = money_over(tmp_path, kinds=(kind,), extra=(poke,))
    await money.open(unit_plan="team")
    loop, owner = money.loop, money.loop.owner
    agent_session_id = await loop.start("asker")
    await loop.say(agent_session_id, "Compute it, and poke it.")
    loop.anthropic.add(
        reply(call("compute", q="everything"), call("poke", q="once")), reply(said("Done."))
    )
    windows = loop.managers.windows
    real = windows.bound_tool_response

    async def lost(*args: object, **kwargs: object) -> object:
        monkeypatch.setattr(windows, "bound_tool_response", real)
        raise RuntimeError("the run is lost here")

    monkeypatch.setattr(windows, "bound_tool_response", lost)
    with pytest.raises(RuntimeError):
        await loop.loops.run(owner, agent_session_id)
    assert len(poke.ran_as) == 1 and loop.jobs["compute"].started == {}
    request = next(
        s
        for s in await loop.history(agent_session_id)
        if isinstance(s.header, ToolRequestHeader) and s.header.tool == "compute"
    )
    await loop.managers.tools.decide_call(owner, agent_session_id, request.seq, approve=True)

    parked = await loop.loops.run(owner, agent_session_id)

    assert parked.park is not None and parked.park.job is not None
    handle = loop.jobs["compute"].started[request.id]
    await loop.loops.complete_job(
        owner, agent_session_id, JobCompletion(key=request.id, handle=handle, text="done")
    )
    done = await loop.loops.run(owner, agent_session_id)
    assert done.outcome is LoopOutcome.SUCCEEDED
    assert len(poke.ran_as) == 1, "the unsafe call ran once"
    assert len(loop.jobs["compute"].deadlines) == 1, "the job started once"
    holds = await money.ledger.read_entries(owner.org_id, kind=EntryKind.HOLD, limit=20)
    jobs = [h.id for h in holds if isinstance(h, FundedHold) and h.hold.purpose == "compute"]
    assert jobs == [parked.park.job.spend_hold_id], "under one hold"


async def test_a_spending_job_after_a_sessions_model_calls_is_judged_by_its_budget_alone(
    tmp_path: Path,
) -> None:
    """A job's worst case is its rate to its deadline, far above any model
    call's: after five calls it still starts, unparked and with no page,
    since no model call's norm judges it."""
    money = money_over(tmp_path, kinds=(ASSISTANT, DELIVERY, BUILDER))
    await money.open(unit_plan="team")
    loop, owner = money.loop, money.loop.owner
    agent_session_id = await loop.start("builder")
    await loop.say(agent_session_id, "Look five things up, then start it.")
    loop.anthropic.add(
        *[reply(use("lookup", q=f"item {i}")) for i in range(5)],
        reply(call("compute", q="everything")),
    )

    parked = await loop.loops.run(owner, agent_session_id)

    assert parked.park is not None and parked.park.reason is ParkReason.JOB
    assert money.pager.pages == []
    assert len(loop.jobs["compute"].deadlines) == 1


# Time zones.


async def test_moving_the_time_zone_never_yields_a_second_days_budget_inside_one_real_day(
    tmp_path: Path,
) -> None:
    """A day's budget spent in UTC+14, then the zone moved to UTC-12 and
    back: every call is refused until a window that starts where the last
    one ended, a whole day of the new zone or more later."""
    money = money_over(tmp_path)
    clock = money.loop.clock
    owner = money.loop.owner
    clock.now = at("2026-10-05T08:00:00")  # 22:00 on 5 October in UTC+14
    await money.open(unit_plan="team", zone=KIRITIMATI)
    budget = make_spend_budget(SpendBudgetScopeKind.TENANT, str(owner.org_id), cost_micros=1_000)
    await money.loop.managers.spend_budgets.create_spend_budget(owner, budget)

    first = await spend(money, 1_000)
    assert first.hold.lines[0].window_start == at("2026-10-04T10:00:00")

    clock.now = at("2026-10-05T08:30:00")
    spend_account = await money.agent_billing.get_spend_account(owner)
    spend_account = await money.agent_billing.set_time_zone(owner, BAKER, spend_account.version)
    for moment in ("2026-10-05T08:45:00", "2026-10-05T11:59:00"):
        clock.now = at(moment)
        refused = await money.gate.authorize(owner, tenant_request(owner, 1))
        assert isinstance(refused, Refusal), f"a second day's budget at {moment}"
        assert refused.breaches[0].resets_at == at("2026-10-05T12:00:00")

    clock.now = at("2026-10-05T12:00:00")  # the first midnight of UTC-12 past the day's end
    second = await spend(money, 1_000)
    assert second.hold.lines[0].window_start == at("2026-10-05T12:00:00")

    clock.now = at("2026-10-06T00:00:00")
    await money.agent_billing.set_time_zone(owner, KIRITIMATI, spend_account.version)
    clock.now = at("2026-10-06T23:00:00")  # a whole day of UTC+14 later, and still the window
    assert isinstance(await money.gate.authorize(owner, tenant_request(owner, 1)), Refusal)
    clock.now = at("2026-10-07T10:00:00")
    third = await spend(money, 1_000)
    assert third.hold.lines[0].window_start == at("2026-10-07T10:00:00")
    spent = await money.agent_billing.get_spend(owner, budget.id)
    assert spent.window_start == at("2026-10-07T10:00:00") and spent.spent_cost_micros == 1_000


@pytest.mark.parametrize("kind", [WindowKind.DAY, WindowKind.WEEK])
def test_windows_tile_time_across_changes_of_zone_and_none_is_shorter_than_its_kind(
    kind: WindowKind,
) -> None:
    """Every hour across a month of zone changes falls in one window; the
    windows meet end to start, and none is shorter than a day or a week."""
    zones = (
        ZoneChange(zone="UTC", at=at("2026-10-01T00:00:00")),
        ZoneChange(zone=KIRITIMATI, at=at("2026-10-03T07:00:00")),
        ZoneChange(zone=BAKER, at=at("2026-10-03T09:00:00")),
        ZoneChange(zone="Asia/Kolkata", at=at("2026-10-12T18:30:00")),
        ZoneChange(zone=KIRITIMATI, at=at("2026-10-20T01:00:00")),
    )
    length = timedelta(days=1) if kind is WindowKind.DAY else timedelta(weeks=1)
    starts: dict[datetime, datetime] = {}
    moment = at("2026-10-01T00:00:00")
    while moment < at("2026-11-01T00:00:00"):
        start, end = zoned_window(kind, zones, moment)
        assert start <= moment < end
        starts[start] = max(end, starts.get(start, end))  # a change lengthens the open window
        moment += timedelta(minutes=30)
    ordered = sorted(starts.items())
    for (start, end), (next_start, _) in pairwise(ordered):
        assert end == next_start, f"a gap or an overlap after {start}"
        assert end - start >= length, f"a window shorter than its kind at {start}"


# Credits and top-ups.


async def test_a_credit_counts_only_once_its_signed_confirmation_checks_out(tmp_path: Path) -> None:
    """A confirmation with no signature, a forged one, a changed body, or a
    stale one posts nothing and the call still parks on its funds; the
    provider's own confirmation posts the credit once, however often it is
    delivered."""
    money = money_over(tmp_path, unit_plans=PREPAID)
    await money.open(unit_plan="prepaid")
    owner = money.loop.owner
    now = money.loop.clock()
    payload, signature = money.payments.confirm(owner.org_id, 10_000, now)
    _, forged = PaymentProviderTwinImpl().confirm(owner.org_id, 10_000, now)
    changed = payload.replace(b"10000", b"99000")
    stale_payload, stale = money.payments.confirm(owner.org_id, 10_000, now - timedelta(hours=1))

    for body, header in (
        (payload, None),
        (payload, forged),
        (changed, signature),
        (stale_payload, stale),
    ):
        with pytest.raises(DeliveryRefused):
            await money.agent_billing.confirm_payment(owner, body, header)
    credits = (await money.agent_billing.get_balances(owner))[2]
    assert credits.added == 0, "nothing counts before a confirmation checks out"
    with pytest.raises(GateParked) as parked:
        await money.gate.authorize(owner, tenant_request(owner, 5_000))
    assert parked.value.park.unlock == FUNDS_UNLOCK and parked.value.park.retry_at is None

    first = await money.agent_billing.confirm_payment(owner, payload, signature)
    again = await money.agent_billing.confirm_payment(owner, payload, signature)

    assert again == first and first.amount_micros == 10_000
    credits = (await money.agent_billing.get_balances(owner))[2]
    assert credits.added == 10_000, "one payment credits once"
    hold = await money.gate.authorize_priced(owner, tenant_request(owner, 5_000), None)
    assert isinstance(hold, FundedHold) and hold.draw.credits == 5_000


async def test_a_confirmation_of_another_tenant_credits_nobody_here(tmp_path: Path) -> None:
    money = money_over(tmp_path, unit_plans=PREPAID)
    await money.open(unit_plan="prepaid")
    payload, signature = money.payments.confirm(new_id(), 10_000, money.loop.clock())
    with pytest.raises(Exception, match="another tenant"):
        await money.agent_billing.confirm_payment(money.loop.owner, payload, signature)
    assert (await money.agent_billing.get_balances(money.loop.owner))[2].added == 0


async def test_a_top_up_leaves_every_limit_as_it_was(tmp_path: Path) -> None:
    """Credit is room in a bucket, never a limit: the budget's amount and
    version stay, its window's spend stays, and the next call is still
    refused by the limit."""
    money = money_over(tmp_path, unit_plans=PREPAID)
    await money.open(unit_plan="prepaid")
    owner = money.loop.owner
    await money.top_up(5_000)
    budget = make_spend_budget(SpendBudgetScopeKind.TENANT, str(owner.org_id), cost_micros=2_000)
    budget = await money.loop.managers.spend_budgets.create_spend_budget(owner, budget)
    await spend(money, 2_000)
    before = await money.agent_billing.get_spend(owner, budget.id)

    await money.top_up(1_000_000)

    after = await money.loop.managers.spend_budgets.get_spend_budget(owner, budget.id)
    assert after.amount == budget.amount and after.version == budget.version
    assert await money.agent_billing.get_spend(owner, budget.id) == before
    refused = await money.gate.authorize(owner, tenant_request(owner, 1_000))
    assert isinstance(refused, Refusal) and refused.breaches[0].spend_budget_id == budget.id


# Who pays.


async def test_a_tenant_nobody_can_name_to_pay_spends_nothing_and_takes_no_platform_key(
    tmp_path: Path,
) -> None:
    """With no spend account, nothing is held, no provider is called, and the
    session parks for a person; an own key with no reference, or a unit plan the
    catalog does not hold, says nobody either."""
    money = money_over(tmp_path)
    agent_session_id = await money.loop.start()
    await money.loop.say(agent_session_id, "What is the total?")
    money.loop.anthropic.add(reply(said("The total is 12.")))

    parked = await money.loop.loops.run(money.loop.owner, agent_session_id)

    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert parked.park.reason is ParkReason.PERSON and parked.park.unlock == SPENDER_UNLOCK
    assert money.loop.anthropic.calls == [] and money.loop.openai.calls == []
    assert await money.ledger.read_entries(money.loop.owner.org_id, limit=10) == []

    own = SpendAccount(
        id=money.loop.owner.org_id,
        created_at=money.loop.clock(),
        updated_at=money.loop.clock(),
        created_by=money.loop.owner.user_id,
        updated_by=money.loop.owner.user_id,
        funding=FundingMode.OWN_KEY,
        key_ref=None,
        unit_plan_id="team",
        unit_plan_version=1,
        period_anchor=money.loop.clock(),
        zones=(ZoneChange(zone="UTC", at=money.loop.clock()),),
    )
    with pytest.raises(SpenderUnknown):
        credential_of(own)
    assert credential_of(own.model_copy(update={"key_ref": "tenant-key-1"})) == "tenant-key-1"
    with pytest.raises(SpenderUnknown):
        credential_of(None)
    await money.spend_accounts.create_spend_account(
        own.id, own.model_copy(update={"funding": FundingMode.PLATFORM, "unit_plan_id": "gone"}), ()
    )
    with pytest.raises(SpenderUnknown):
        await money.gate.authorize(money.loop.owner, tenant_request(money.loop.owner, 1_000))
    assert await money.ledger.read_entries(money.loop.owner.org_id, limit=10) == []


async def test_an_own_key_tenant_spends_nothing_until_its_key_reaches_the_call(
    tmp_path: Path,
) -> None:
    """The loop calls the provider on the platform's key alone, so a tenant
    on its own key, named and all, is refused: no provider call, no ledger
    entry, and the session parks for a person."""
    money = money_over(tmp_path)
    await money.open(funding=FundingMode.OWN_KEY, key_ref="tenant-key-1")
    agent_session_id = await money.loop.start()
    await money.loop.say(agent_session_id, "What is the total?")
    money.loop.anthropic.add(reply(said("The total is 12.")))

    parked = await money.loop.loops.run(money.loop.owner, agent_session_id)

    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert parked.park.reason is ParkReason.PERSON and parked.park.unlock == SPENDER_UNLOCK
    assert money.loop.anthropic.calls == [] and money.loop.openai.calls == []
    assert await money.ledger.read_entries(money.loop.owner.org_id, limit=10) == []


# Rate limits and spend limits.


async def test_a_rate_limit_parks_on_the_provider_and_is_told_as_a_rate_limit(
    tmp_path: Path,
) -> None:
    """Both providers answer `rate_limited` until the retries are spent: the
    session parks on the provider, with a retry time, and is told the
    provider's pace, never a budget; a top-up leaves it parked."""
    money = money_over(tmp_path)
    await money.open(unit_plan="team")
    agent_session_id = await money.loop.start()
    await money.loop.say(agent_session_id, "What is the total?")
    limited = ScriptedFailure(kind=ErrorKind.RATE_LIMITED, retry_after=2)
    money.loop.anthropic.add(limited, limited, limited)
    money.loop.openai.add(limited, limited, limited)

    parked = await money.loop.loops.run(money.loop.owner, agent_session_id)

    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert parked.park.reason is ParkReason.PROVIDER, "a rate limit is the provider's"
    assert parked.park.unlock == ProviderName.OPENAI.value and parked.park.retry_at is not None
    told = notice_of(parked.park)
    assert told.limit is LimitKind.RATE
    assert not any(word in told.text.lower() for word in ("budget", "balance", "spending"))

    await money.top_up(1_000_000)
    session = await money.loop.managers.agent_sessions.get_agent_session(
        money.loop.owner, agent_session_id
    )
    assert session.status is AgentSessionStatus.PARKED and session.park == parked.park


@pytest.mark.parametrize("by", ["funds", "limit"])
async def test_a_spend_limit_parks_on_its_budget_and_is_told_as_a_spend_limit(
    tmp_path: Path, by: str
) -> None:
    """Funds no bucket covers, or a budget the call breaches: the session
    parks on the budget before any call, and is told a spending limit,
    never the provider's pace."""
    money = money_over(tmp_path, unit_plans=PREPAID)
    await money.open(unit_plan="prepaid")
    owner = money.loop.owner
    if by == "limit":
        await money.top_up(10_000_000)
        budget = make_spend_budget(SpendBudgetScopeKind.TENANT, str(owner.org_id), cost_micros=1)
        await money.loop.managers.spend_budgets.create_spend_budget(owner, budget)
    agent_session_id = await money.loop.start()
    await money.loop.say(agent_session_id, "What is the total?")
    money.loop.anthropic.add(reply(said("The total is 12.")))

    parked = await money.loop.loops.run(owner, agent_session_id)

    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert parked.park.reason is ParkReason.SPEND_BUDGET, "a spend limit is the budget's"
    if by == "funds":
        assert parked.park.unlock == FUNDS_UNLOCK
    assert money.loop.anthropic.calls == []
    told = notice_of(parked.park)
    assert told.limit is LimitKind.SPEND
    assert not any(word in told.text.lower() for word in ("rate", "provider", "pace"))


# A call no price gives a cost: the operator prices its model in a release.


class Releases(PriceBookInterface):
    """The price book across releases: the table one release reads, then,
    once `release` is called, the next one's, in place of a new process."""

    def __init__(self, table: PriceTable) -> None:
        self._book = PriceBookTableImpl((table,))

    def release(self, table: PriceTable) -> None:
        self._book = PriceBookTableImpl((table,))

    @property
    def version(self) -> str:
        return self._book.version

    def price_of(self, provider: str, model: str) -> ModelPrice | None:
        return self._book.price_of(provider, model)

    def price_at(self, version: str, provider: str, model: str) -> ModelPrice | None:
        return self._book.price_at(version, provider, model)


@pytest.mark.parametrize("by", ["funds", "limit"])
async def test_a_call_no_price_covers_parks_until_a_release_prices_its_model(
    tmp_path: Path, by: str
) -> None:
    """The table in force prices every model but the one the session calls:
    whether the buckets or a cost budget meet it first, the session parks on
    the price before any call, says an operator prices the model, and tries
    again by itself. A release prices it, and the next try calls."""
    first = LIST_PRICES.model_copy(update={"version": "2026-09-01"})
    book = Releases(first)
    money = money_over(tmp_path, prices=book)
    await money.open(unit_plan="team")
    owner = money.loop.owner
    agent_session_id = await money.loop.start()
    fills = await money.loop.managers.language_models.resolve_fill_set(
        owner, agent_session_id, ASSISTANT.roles, Eligibility()
    )
    fill = fills.fill_for(MAIN)
    assert fill is not None
    rows = tuple(row for row in LIST_PRICES.rows if row.model != fill.model)
    book.release(first.model_copy(update={"rows": rows}))
    if by == "limit":
        budget = make_spend_budget(
            SpendBudgetScopeKind.TENANT, str(owner.org_id), cost_micros=10**9
        )
        await money.loop.managers.spend_budgets.create_spend_budget(owner, budget)
    await money.loop.say(agent_session_id, "What is the total?")

    parked = await money.loop.loops.run(owner, agent_session_id)

    park = parked.park
    assert parked.end is RunEnd.PARKED and park is not None
    assert (park.reason, park.unlock) == (ParkReason.SPEND_BUDGET, PRICE_UNLOCK)
    assert park.retry_at is not None
    assert park.retry_at == money.loop.clock() + PRICE_RETRY, "it tries again by itself"
    assert park.cause is not None and "an operator of the platform prices it" in park.cause
    told = notice_of(park)
    assert told.limit is LimitKind.SPEND and "an operator of the platform" in told.text
    assert money.loop.anthropic.calls == []

    book.release(LIST_PRICES)
    money.loop.clock.now = park.retry_at
    money.loop.anthropic.add(reply(said("The total is 12.")))
    # Its retry time: the sweep wakes a session still parked on its park.
    await money.loop.managers.agent_sessions.wake_agent_session(owner, agent_session_id, park)
    resumed = await money.loop.loops.run(owner, agent_session_id)

    assert (resumed.end, resumed.outcome) == (RunEnd.ENDED, LoopOutcome.SUCCEEDED), resumed
    assert len(money.loop.anthropic.calls) == 1


# The anomaly guard.


async def test_a_call_far_above_its_sessions_norm_parks_for_a_person_and_pages_the_operator(
    tmp_path: Path,
) -> None:
    """After a run of small calls, a model call whose worst case is far above
    them parks the session for a person before anything is held or called,
    and pages the operator. A person's approval lets that one call through."""
    guard = AnomalyGuard(factor=10, min_calls=3, floor_micros=0)
    money = money_over(tmp_path, options=MoneyGateOptions(guard=guard))
    await money.open(unit_plan="enterprise")
    owner = money.loop.owner
    agent_session_id = await money.loop.start()
    for _ in range(4):
        await spend(money, 1_000, agent_session_id=agent_session_id)
    await money.loop.say(agent_session_id, "Read every record, twice.")
    money.loop.anthropic.add(reply(said("Done.")))
    held_before = await money.ledger.read_entries(owner.org_id, kind=EntryKind.HOLD, limit=50)

    parked = await money.loop.loops.run(owner, agent_session_id)

    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert parked.park.reason is ParkReason.PERSON and parked.park.unlock == ANOMALY_UNLOCK
    assert notice_of(parked.park).limit is LimitKind.PERSON
    assert money.loop.anthropic.calls == []
    assert (
        await money.ledger.read_entries(owner.org_id, kind=EntryKind.HOLD, limit=50) == held_before
    )
    (page,) = money.pager.pages
    assert page.agent_session_id == agent_session_id and page.norm_micros == 1_000
    assert page.expected_micros > 10 * page.norm_micros

    approval = await money.agent_billing.approve_call(owner, agent_session_id, page.expected_micros)
    resumed = await money.loop.loops.run(owner, agent_session_id)

    assert resumed.end is RunEnd.ENDED, resumed
    holds = await money.ledger.read_entries(owner.org_id, kind=EntryKind.HOLD, limit=50)
    assert isinstance(holds[0], FundedHold) and holds[0].approval_id == approval.id
    with pytest.raises(GateParked):
        await money.gate.authorize(
            owner, tenant_request(owner, page.expected_micros, agent_session_id=agent_session_id)
        )
    assert len(money.pager.pages) == 2, "an approval lets one call through"
