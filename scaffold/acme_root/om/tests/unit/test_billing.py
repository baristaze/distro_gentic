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
from contracts.benchmark_storage import operator
from contracts.budget_storage import make_budget
from contracts.loops import ASSISTANT, reply, said
from contracts.money import Money, money_over
from contracts.project_storage import in_project

from acme.integrations.exceptions import DeliveryRefused
from acme.integrations.model_providers.calls import ModelCall
from acme.integrations.model_providers.scripted import ScriptedFailure
from acme.integrations.model_providers.types import ErrorKind, ProviderName, Usage
from acme.integrations.payments.twin import PaymentProviderTwinImpl
from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.agents.loop_rules import SPENDER_UNLOCK
from acme.om.agents.types.run import RunEnd
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import new_id
from acme.om.billing.impl.gate import MoneyCallGateImpl, MoneyGateOptions
from acme.om.billing.impl.prices import PriceBookTableImpl
from acme.om.billing.rules import (
    ANOMALY_UNLOCK,
    FUNDS_UNLOCK,
    HELD_UNLOCK,
    AnomalyGuard,
    LimitKind,
    credential_of,
    notice_of,
    units_of,
    zoned_window,
)
from acme.om.billing.types.account import Account, FundingMode, ZoneChange
from acme.om.billing.types.ledger import Charge, EntryKind, FundedHold, PricedAt
from acme.om.billing.types.plan import UNITS, Plan, PlanCatalog
from acme.om.budgets.impl.pricing import LIST_PRICES
from acme.om.budgets.pricing import ModelPrice, PriceRow, PriceTable, Rates
from acme.om.budgets.rules import call_exposure, usage_spend
from acme.om.budgets.types.amount import Spend
from acme.om.budgets.types.breach import Refusal
from acme.om.budgets.types.budget import BudgetScope, BudgetScopeKind, WindowKind
from acme.om.budgets.types.hold import Billed, HoldRequest, Settlement
from acme.om.context import OperatorPermission, OperatorRole, TenantContext
from acme.om.exceptions import BudgetRefused, GateParked, NotAuthorized, SpenderUnknown
from acme.om.models.types.fill import MAIN, Eligibility
from acme.om.projects.impl.policies import SessionProjectsBoundImpl
from acme.om.steps.types.header import ParkReason
from acme.om.windows.gate import CallGateInterface
from acme.om.windows.impl.gate import CallGateBudgetImpl
from acme.om.windows.rules import call_shape

PREPAID = PlanCatalog(
    plans=(Plan(id="prepaid", version=1, included_units=0, unit_price_micros=1_000),)
)
"""A plan that includes nothing: every unit is paid from a money bucket."""

KIRITIMATI = "Pacific/Kiritimati"  # UTC+14, no daylight saving
BAKER = "Etc/GMT+12"  # UTC-12, no daylight saving


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def spender(ctx: TenantContext) -> Principal:
    return Principal(kind=PrincipalKind.PERSON, id=ctx.user_id)


def tenant_request(
    ctx: TenantContext, cost_micros: int, *, session_id: UUID | None = None
) -> HoldRequest:
    """A call charged to the tenant's scope, at a worst case of `cost_micros`."""
    return HoldRequest(
        spender_id=ctx.user_id,
        scopes=(BudgetScope(kind=BudgetScopeKind.TENANT, key=str(ctx.org_id)),),
        exposure=Spend(cost_micros=cost_micros, tokens=0),
        session_id=session_id,
        purpose=MAIN,
    )


async def spend(money: Money, cost_micros: int, *, session_id: UUID | None = None) -> FundedHold:
    """A call that fits, held and settled at its whole worst case."""
    owner = money.loop.owner
    hold = await money.gate.authorize_priced(
        owner, tenant_request(owner, cost_micros, session_id=session_id), None
    )
    assert isinstance(hold, FundedHold), hold
    await money.gate.settle(owner, hold.id, Billed(usage=hold.hold.exposure))
    return hold


async def entries_of(money: Money, hold_id: UUID) -> dict[str, object]:
    found = await money.ledger.read_entries(money.loop.owner.org_id, hold_id=hold_id, limit=10)
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
    await money.open(plan="team")
    owner = money.loop.owner
    session_id = await money.loop.start()
    fills = await money.loop.managers.models.resolve_fill_set(
        owner, session_id, ASSISTANT.roles, Eligibility()
    )
    fill = fills.fill_for(MAIN)
    assert fill is not None
    call = ModelCall(model=fill.model, messages=(), max_output_tokens=4_000)
    first = money.prices.price_at(LIST_PRICES.version, fill.provider.value, fill.model)
    assert first is not None

    hold_id = await money.calls.authorize(
        owner, session_id, spender(owner), MAIN, fill, call, credential="platform"
    )

    hold = await money.gate.read_hold(owner, hold_id)
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
        SessionProjectsBoundImpl(money.loop.storage.get_project_storage()),
    )
    usage = Usage(input=120_000, output=3_000)
    await next_process.settle(owner, hold_id, usage, billed=True)

    found = await entries_of(money, hold_id)
    settlement, charge = found["Settlement"], found["Charge"]
    assert isinstance(settlement, Settlement) and isinstance(charge, Charge)
    billed = usage_spend(usage, first)
    assert settlement.spent == billed, "the bill read the row the cap read"
    assert charge.price_version == LIST_PRICES.version
    assert charge.units == units_of(billed.cost_micros, UNITS.micros_per_unit)
    newer = usage_spend(usage, book.price_at(later.version, fill.provider.value, fill.model))
    assert charge.units != units_of(newer.cost_micros, UNITS.micros_per_unit), "the rows differ"


async def test_a_hold_a_settlement_and_a_charge_post_to_the_one_ledger(tmp_path: Path) -> None:
    """A loop's model call holds, settles, and is charged in the one ledger,
    and the engine's own ledger holds none of it."""
    money = money_over(tmp_path)
    await money.open(plan="team")
    session_id = await money.loop.start()
    await money.loop.say(session_id, "What is the total?")
    money.loop.anthropic.add(reply(said("The total is 12.")))

    ran = await money.loop.loops.run(money.loop.owner, session_id)

    assert ran.end is RunEnd.ENDED, ran
    org = money.loop.owner.org_id
    (hold,) = await money.ledger.read_entries(org, kind=EntryKind.HOLD, limit=10)
    assert isinstance(hold, FundedHold) and hold.session_id == session_id
    found = await entries_of(money, hold.id)
    assert sorted(found) == ["Charge", "FundedHold", "Settlement"]
    charge = found["Charge"]
    assert isinstance(charge, Charge) and charge.units > 0 and charge.amount_micros == 0, (
        "the plan's included units paid for it"
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
    await money.open(plan="team")
    session_id = await money.loop.start()
    await money.loop.say(session_id, "What is the total?")
    money.loop.anthropic.add(reply(said("The total is 12.")))
    assert (await money.loop.loops.run(money.loop.owner, session_id)).end is RunEnd.ENDED
    org = money.loop.owner.org_id
    reader = operator(OperatorRole.READ)

    page = await money.billing.get_entries(reader, org, limit=50)
    assert not page.has_more
    assert sorted(type(entry).__name__ for entry in page.items) == [
        "Charge",
        "FundedHold",
        "Settlement",
    ]
    (charge,) = (
        await money.billing.get_entries(reader, org, kind=EntryKind.CHARGE, limit=50)
    ).items
    assert isinstance(charge, Charge)
    (hold,) = (await money.billing.get_entries(reader, org, session_id=session_id, limit=50)).items
    assert isinstance(hold, FundedHold)
    of_hold = await money.billing.get_entries(reader, org, hold_id=hold.id, limit=50)
    assert sorted(type(entry).__name__ for entry in of_hold.items) == [
        "Charge",
        "FundedHold",
        "Settlement",
    ]
    cut = await money.billing.get_entries(reader, org, limit=2)
    assert len(cut.items) == 2 and cut.has_more
    elsewhere = await money.billing.get_entries(reader, new_id(), limit=50)
    assert elsewhere.items == () and not elsewhere.has_more
    minting = reader.model_copy(update={"permissions": frozenset({OperatorPermission.MINT})})
    with pytest.raises(NotAuthorized):
        await money.billing.get_entries(minting, org, limit=50)


async def test_the_buckets_are_drawn_in_their_fixed_order_and_prepaid_differs_only_in_which_pays(
    tmp_path: Path,
) -> None:
    """Included units first, then granted units, then credits; a call no
    bucket covers parks on the budget, naming the funds."""
    plans = PlanCatalog(
        plans=(Plan(id="small", version=1, included_units=3, unit_price_micros=1_000),)
    )
    money = money_over(tmp_path, plans=plans)
    await money.open(plan="small")
    owner = money.loop.owner
    await money.top_up(2_000)

    hold = await spend(money, 5_000)  # 5 units: 3 included, then 2 from credits

    assert hold.draw.included == 3 and hold.draw.granted == 0 and hold.draw.credits == 2_000
    with pytest.raises(GateParked) as parked:
        await money.gate.authorize(owner, tenant_request(owner, 1_000))
    assert parked.value.park.reason is ParkReason.BUDGET
    assert parked.value.park.unlock == FUNDS_UNLOCK
    assert parked.value.park.retry_at is not None, "the next billing period refills the plan"


async def test_a_call_short_only_of_what_open_holds_reserve_tries_again_soon(
    tmp_path: Path,
) -> None:
    """Ten included units, eight held by a call still open: a call for five
    parks on the budget and tries again within seconds, not at the period's
    end, and fits once the open call settles."""
    plans = PlanCatalog(
        plans=(Plan(id="ten", version=1, included_units=10, unit_price_micros=1_000),)
    )
    money = money_over(tmp_path, plans=plans)
    await money.open(plan="ten")
    owner = money.loop.owner
    first = await money.gate.authorize_priced(owner, tenant_request(owner, 8_000), None)
    assert isinstance(first, FundedHold) and first.draw.included == 8

    with pytest.raises(GateParked) as parked:
        await money.gate.authorize_priced(owner, tenant_request(owner, 5_000), None)

    park = parked.value.park
    assert park.reason is ParkReason.BUDGET and park.unlock == HELD_UNLOCK
    assert park.retry_at is not None
    assert park.retry_at - money.loop.clock() <= timedelta(seconds=30), (
        "soon, never the period's end"
    )
    assert notice_of(park).limit is LimitKind.SPEND
    await money.gate.settle(owner, first.id, Billed(usage=Spend(cost_micros=3_000, tokens=0)))
    second = await money.gate.authorize_priced(owner, tenant_request(owner, 5_000), None)
    assert isinstance(second, FundedHold) and second.draw.included == 5


# A project's budget binds its sessions.


@pytest.mark.parametrize("gate", ["money", "engine"])
async def test_a_projects_budget_refuses_a_call_its_tenants_has_room_for(
    gate: str, tmp_path: Path
) -> None:
    """The call is charged to the project its session belongs to, as the
    projects answer it: past the project's budget it is refused, with the
    project's line its one breach, while the tenant's budget has room. A
    session of no project is charged to none, and the same call is held."""
    money = money_over(tmp_path)
    await money.open(plan="team")
    loop, owner = money.loop, money.loop.owner
    calls: CallGateInterface = money.calls
    if gate == "engine":
        calls = CallGateBudgetImpl(
            loop.managers.budget_gate,
            loop.managers.pricing,
            loop.managers.agent_sessions,
            SessionProjectsBoundImpl(loop.storage.get_project_storage()),
        )
    ours, loose = await loop.start(), await loop.start()
    project = await in_project(loop.storage.get_project_storage(), owner.org_id, ours)
    for kind, key, cap in (
        (BudgetScopeKind.TENANT, str(owner.org_id), 1_000_000_000),
        (BudgetScopeKind.PROJECT, str(project), 1),
    ):
        await loop.managers.budgets.create_budget(owner, make_budget(kind, key, cost_micros=cap))
    fills = await loop.managers.models.resolve_fill_set(owner, ours, ASSISTANT.roles, Eligibility())
    fill = fills.fill_for(MAIN)
    assert fill is not None
    call = ModelCall(model=fill.model, messages=(), max_output_tokens=4_000)

    with pytest.raises(BudgetRefused) as refused:
        await calls.authorize(owner, ours, spender(owner), MAIN, fill, call, credential="platform")
    (breach,) = refused.value.refusal.breaches
    assert breach.scope == BudgetScope(kind=BudgetScopeKind.PROJECT, key=str(project))

    held = await calls.authorize(
        owner, loose, spender(owner), MAIN, fill, call, credential="platform"
    )
    await calls.settle(owner, held, None, billed=False)


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
    await money.open(plan="team", zone=KIRITIMATI)
    budget = make_budget(BudgetScopeKind.TENANT, str(owner.org_id), cost_micros=1_000)
    await money.loop.managers.budgets.create_budget(owner, budget)

    first = await spend(money, 1_000)
    assert first.hold.lines[0].window_start == at("2026-10-04T10:00:00")

    clock.now = at("2026-10-05T08:30:00")
    account = await money.billing.get_account(owner)
    account = await money.billing.set_time_zone(owner, BAKER, account.version)
    for moment in ("2026-10-05T08:45:00", "2026-10-05T11:59:00"):
        clock.now = at(moment)
        refused = await money.gate.authorize(owner, tenant_request(owner, 1))
        assert isinstance(refused, Refusal), f"a second day's budget at {moment}"
        assert refused.breaches[0].resets_at == at("2026-10-05T12:00:00")

    clock.now = at("2026-10-05T12:00:00")  # the first midnight of UTC-12 past the day's end
    second = await spend(money, 1_000)
    assert second.hold.lines[0].window_start == at("2026-10-05T12:00:00")

    clock.now = at("2026-10-06T00:00:00")
    await money.billing.set_time_zone(owner, KIRITIMATI, account.version)
    clock.now = at("2026-10-06T23:00:00")  # a whole day of UTC+14 later, and still the window
    assert isinstance(await money.gate.authorize(owner, tenant_request(owner, 1)), Refusal)
    clock.now = at("2026-10-07T10:00:00")
    third = await spend(money, 1_000)
    assert third.hold.lines[0].window_start == at("2026-10-07T10:00:00")
    spent = await money.billing.get_spend(owner, budget.id)
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
    money = money_over(tmp_path, plans=PREPAID)
    await money.open(plan="prepaid")
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
            await money.billing.confirm_payment(owner, body, header)
    credits = (await money.billing.get_balances(owner))[2]
    assert credits.added == 0, "nothing counts before a confirmation checks out"
    with pytest.raises(GateParked) as parked:
        await money.gate.authorize(owner, tenant_request(owner, 5_000))
    assert parked.value.park.unlock == FUNDS_UNLOCK and parked.value.park.retry_at is None

    first = await money.billing.confirm_payment(owner, payload, signature)
    again = await money.billing.confirm_payment(owner, payload, signature)

    assert again == first and first.amount_micros == 10_000
    credits = (await money.billing.get_balances(owner))[2]
    assert credits.added == 10_000, "one payment credits once"
    hold = await money.gate.authorize_priced(owner, tenant_request(owner, 5_000), None)
    assert isinstance(hold, FundedHold) and hold.draw.credits == 5_000


async def test_a_confirmation_of_another_tenant_credits_nobody_here(tmp_path: Path) -> None:
    money = money_over(tmp_path, plans=PREPAID)
    await money.open(plan="prepaid")
    payload, signature = money.payments.confirm(new_id(), 10_000, money.loop.clock())
    with pytest.raises(Exception, match="another tenant"):
        await money.billing.confirm_payment(money.loop.owner, payload, signature)
    assert (await money.billing.get_balances(money.loop.owner))[2].added == 0


async def test_a_top_up_leaves_every_limit_as_it_was(tmp_path: Path) -> None:
    """Credit is room in a bucket, never a limit: the budget's amount and
    version stay, its window's spend stays, and the next call is still
    refused by the limit."""
    money = money_over(tmp_path, plans=PREPAID)
    await money.open(plan="prepaid")
    owner = money.loop.owner
    await money.top_up(5_000)
    budget = make_budget(BudgetScopeKind.TENANT, str(owner.org_id), cost_micros=2_000)
    budget = await money.loop.managers.budgets.create_budget(owner, budget)
    await spend(money, 2_000)
    before = await money.billing.get_spend(owner, budget.id)

    await money.top_up(1_000_000)

    after = await money.loop.managers.budgets.get_budget(owner, budget.id)
    assert after.amount == budget.amount and after.version == budget.version
    assert await money.billing.get_spend(owner, budget.id) == before
    refused = await money.gate.authorize(owner, tenant_request(owner, 1_000))
    assert isinstance(refused, Refusal) and refused.breaches[0].budget_id == budget.id


# Who pays.


async def test_a_tenant_nobody_can_name_to_pay_spends_nothing_and_takes_no_platform_key(
    tmp_path: Path,
) -> None:
    """With no account, nothing is held, no provider is called, and the
    session parks for a person; an own key with no reference, or a plan the
    catalog does not hold, says nobody either."""
    money = money_over(tmp_path)
    session_id = await money.loop.start()
    await money.loop.say(session_id, "What is the total?")
    money.loop.anthropic.add(reply(said("The total is 12.")))

    parked = await money.loop.loops.run(money.loop.owner, session_id)

    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert parked.park.reason is ParkReason.PERSON and parked.park.unlock == SPENDER_UNLOCK
    assert money.loop.anthropic.calls == [] and money.loop.openai.calls == []
    assert await money.ledger.read_entries(money.loop.owner.org_id, limit=10) == []

    own = Account(
        id=money.loop.owner.org_id,
        created_at=money.loop.clock(),
        updated_at=money.loop.clock(),
        created_by=money.loop.owner.user_id,
        updated_by=money.loop.owner.user_id,
        funding=FundingMode.OWN_KEY,
        key_ref=None,
        plan_id="team",
        plan_version=1,
        period_anchor=money.loop.clock(),
        zones=(ZoneChange(zone="UTC", at=money.loop.clock()),),
    )
    with pytest.raises(SpenderUnknown):
        credential_of(own)
    assert credential_of(own.model_copy(update={"key_ref": "tenant-key-1"})) == "tenant-key-1"
    with pytest.raises(SpenderUnknown):
        credential_of(None)
    await money.accounts.create_account(
        own.id, own.model_copy(update={"funding": FundingMode.PLATFORM, "plan_id": "gone"}), ()
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
    session_id = await money.loop.start()
    await money.loop.say(session_id, "What is the total?")
    money.loop.anthropic.add(reply(said("The total is 12.")))

    parked = await money.loop.loops.run(money.loop.owner, session_id)

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
    await money.open(plan="team")
    session_id = await money.loop.start()
    await money.loop.say(session_id, "What is the total?")
    limited = ScriptedFailure(kind=ErrorKind.RATE_LIMITED, retry_after=2)
    money.loop.anthropic.add(limited, limited, limited)
    money.loop.openai.add(limited, limited, limited)

    parked = await money.loop.loops.run(money.loop.owner, session_id)

    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert parked.park.reason is ParkReason.PROVIDER, "a rate limit is the provider's"
    assert parked.park.unlock == ProviderName.OPENAI.value and parked.park.retry_at is not None
    told = notice_of(parked.park)
    assert told.limit is LimitKind.RATE
    assert not any(word in told.text.lower() for word in ("budget", "balance", "spending"))

    await money.top_up(1_000_000)
    session = await money.loop.managers.agent_sessions.get_session(money.loop.owner, session_id)
    assert session.status is SessionStatus.PARKED and session.park == parked.park


@pytest.mark.parametrize("by", ["funds", "limit"])
async def test_a_spend_limit_parks_on_its_budget_and_is_told_as_a_spend_limit(
    tmp_path: Path, by: str
) -> None:
    """Funds no bucket covers, or a budget the call breaches: the session
    parks on the budget before any call, and is told a spending limit,
    never the provider's pace."""
    money = money_over(tmp_path, plans=PREPAID)
    await money.open(plan="prepaid")
    owner = money.loop.owner
    if by == "limit":
        await money.top_up(10_000_000)
        budget = make_budget(BudgetScopeKind.TENANT, str(owner.org_id), cost_micros=1)
        await money.loop.managers.budgets.create_budget(owner, budget)
    session_id = await money.loop.start()
    await money.loop.say(session_id, "What is the total?")
    money.loop.anthropic.add(reply(said("The total is 12.")))

    parked = await money.loop.loops.run(owner, session_id)

    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert parked.park.reason is ParkReason.BUDGET, "a spend limit is the budget's"
    if by == "funds":
        assert parked.park.unlock == FUNDS_UNLOCK
    assert money.loop.anthropic.calls == []
    told = notice_of(parked.park)
    assert told.limit is LimitKind.SPEND
    assert not any(word in told.text.lower() for word in ("rate", "provider", "pace"))


# The anomaly guard.


async def test_a_call_far_above_its_sessions_norm_parks_for_a_person_and_pages_the_operator(
    tmp_path: Path,
) -> None:
    """After a run of small calls, a model call whose worst case is far above
    them parks the session for a person before anything is held or called,
    and pages the operator. A person's approval lets that one call through."""
    guard = AnomalyGuard(factor=10, min_calls=3, floor_micros=0)
    money = money_over(tmp_path, options=MoneyGateOptions(guard=guard))
    await money.open(plan="enterprise")
    owner = money.loop.owner
    session_id = await money.loop.start()
    for _ in range(4):
        await spend(money, 1_000, session_id=session_id)
    await money.loop.say(session_id, "Read every record, twice.")
    money.loop.anthropic.add(reply(said("Done.")))
    held_before = await money.ledger.read_entries(owner.org_id, kind=EntryKind.HOLD, limit=50)

    parked = await money.loop.loops.run(owner, session_id)

    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert parked.park.reason is ParkReason.PERSON and parked.park.unlock == ANOMALY_UNLOCK
    assert notice_of(parked.park).limit is LimitKind.PERSON
    assert money.loop.anthropic.calls == []
    assert (
        await money.ledger.read_entries(owner.org_id, kind=EntryKind.HOLD, limit=50) == held_before
    )
    (page,) = money.pager.pages
    assert page.session_id == session_id and page.norm_micros == 1_000
    assert page.expected_micros > 10 * page.norm_micros

    approval = await money.billing.approve_call(owner, session_id, page.expected_micros)
    resumed = await money.loop.loops.run(owner, session_id)

    assert resumed.end is RunEnd.ENDED, resumed
    holds = await money.ledger.read_entries(owner.org_id, kind=EntryKind.HOLD, limit=50)
    assert isinstance(holds[0], FundedHold) and holds[0].approval_id == approval.id
    with pytest.raises(GateParked):
        await money.gate.authorize(
            owner, tenant_request(owner, page.expected_micros, session_id=session_id)
        )
    assert len(money.pager.pages) == 2, "an approval lets one call through"
