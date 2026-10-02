"""Pure rules of billing: the windows a limit counts in, who pays, the unit,
the buckets a hold draws and a settlement takes, the charge, the anomaly
guard, and what a person is told of each park. Values in, values out; no
clock, no storage. Both ledgers ask `open_answer` and `moved` under their
lock before they write."""

import statistics
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field

from acme.om.base import Platform
from acme.om.billing.types.account import PLATFORM_KEY, Account, FundingMode, ZoneChange
from acme.om.billing.types.ledger import (
    BUCKET_ORDER,
    MONEY_BUCKETS,
    NO_DRAW,
    Bucket,
    Charge,
    Count,
    Draw,
    FundedHold,
    Funding,
    Shortfall,
    Turned,
)
from acme.om.billing.types.plan import PlanCatalog, UnitScale
from acme.om.budgets.rules import EPOCH, breaches, window_bounds
from acme.om.budgets.types.amount import Amount
from acme.om.budgets.types.breach import Refusal
from acme.om.budgets.types.budget import Budget, BudgetWindow, WindowKind
from acme.om.budgets.types.hold import HoldLine, Settlement, Tally
from acme.om.exceptions import SpenderUnknown
from acme.om.steps.types.header import Park, ParkReason

FUNDS_UNLOCK = "funds"
"""A budget park's unlock when no bucket covers the call: a top-up, a
grant, or the next billing period."""

PRICE_UNLOCK = "price"
"""A budget park's unlock when no price gives the call a cost in units."""

ANOMALY_UNLOCK = "anomaly"
"""A person park's unlock when a call's expected cost is far above its
session's norm: a person's approval."""

# Windows.


def calendar(kind: WindowKind, zone: str, at: datetime) -> tuple[datetime, datetime]:
    """The day, or the week from Monday, that `at` falls in on the clocks of
    `zone`, as instants. A day across a change of daylight saving is the
    23 or 25 hours the zone's clocks give it."""
    local = at.astimezone(ZoneInfo(zone))
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind is WindowKind.WEEK:
        start, length = day - timedelta(days=local.weekday()), timedelta(weeks=1)
    else:
        start, length = day, timedelta(days=1)
    # Arithmetic on a zoned time moves its wall clock, so a day is the zone's
    # own day across a change of daylight saving.
    return start.astimezone(UTC), (start + length).astimezone(UTC)


def zoned_window(
    kind: WindowKind, zones: Sequence[ZoneChange], at: datetime
) -> tuple[datetime, datetime]:
    """The day or week window `at` falls in, given the tenant's zones in the
    order it set them. The first is the tenant's zone from the start; each
    one after it is a change.

    A change never opens a window: the window open when it lands keeps its
    start, and ends at the first boundary of the new zone at or after the
    end it had. So no window is shorter than the zone's own day or week, no
    two overlap, and moving the zone never yields a second day's budget
    inside one real day."""
    in_force = [change for change in zones if change.at <= at] or list(zones[:1])
    if len(in_force) <= 1:
        return calendar(kind, in_force[0].zone if in_force else "UTC", at)
    last = in_force[-1]
    start, end = zoned_window(kind, in_force[:-1], last.at)
    fresh_start, fresh_end = calendar(kind, last.zone, end)
    boundary = end if fresh_start == end else fresh_end
    if at < boundary:
        return start, boundary
    return calendar(kind, last.zone, at)


def add_months(anchor: datetime, months: int) -> datetime:
    """`anchor` moved by whole months, its day held to the month's last."""
    index = anchor.year * 12 + anchor.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    following = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=UTC)
    last_day = (following - timedelta(days=1)).day
    return anchor.astimezone(UTC).replace(year=year, month=month, day=min(anchor.day, last_day))


def billing_period(anchor: datetime, at: datetime) -> tuple[datetime, datetime]:
    """The billing period `at` falls in: a month from the account's anchor,
    and each month after it."""
    at = at.astimezone(UTC)
    months = (at.year - anchor.year) * 12 + (at.month - anchor.month)
    while add_months(anchor, months) > at:
        months -= 1
    while add_months(anchor, months + 1) <= at:
        months += 1
    return add_months(anchor, months), add_months(anchor, months + 1)


def window_of(
    window: BudgetWindow, account: Account, at: datetime
) -> tuple[datetime, datetime | None]:
    """The start of the window `at` falls in, and when it resets (None for
    one that never does). Days and weeks follow the tenant's time zone,
    months its billing period; an hour, a custom span, and a whole life are
    the engine's own."""
    match window.kind:
        case WindowKind.DAY | WindowKind.WEEK:
            return zoned_window(window.kind, account.zones, at)
        case WindowKind.MONTH:
            return billing_period(account.period_anchor, at)
        case WindowKind.LIFE | WindowKind.HOUR | WindowKind.SPAN:
            return window_bounds(window, at)


def lines_of(budgets: Iterable[Budget], account: Account, now: datetime) -> tuple[HoldLine, ...]:
    """Each budget as a line of a hold made at `now`, in its window as the
    tenant counts it, in the order the ledger locks them: by budget."""
    lines = []
    for budget in sorted(budgets, key=lambda b: b.id):
        start, resets_at = window_of(budget.window, account, now)
        lines.append(
            HoldLine(
                budget_id=budget.id,
                scope=budget.scope,
                window_start=start,
                resets_at=resets_at,
                amount=budget.amount,
            )
        )
    return tuple(lines)


# Who pays.


def credential_of(account: Account | None) -> str:
    """The credential a call of the tenant runs on: the platform's key, or
    the tenant's own key's reference. An account that cannot say is
    `SpenderUnknown`; nothing falls back to the platform's key."""
    if account is None:
        raise SpenderUnknown("the tenant has no billing account; nothing is spent")
    match account.funding:
        case FundingMode.PLATFORM:
            return PLATFORM_KEY
        case FundingMode.OWN_KEY:
            if account.key_ref is None:
                raise SpenderUnknown("the tenant's own key is not named; nothing is spent")
            return account.key_ref


def funding_of(
    account: Account | None, plans: PlanCatalog, units: UnitScale, now: datetime
) -> Funding:
    """The account as one hold carries it. An account that is missing, whose
    funding names no key, or whose plan the catalog does not hold, cannot
    say who pays: `SpenderUnknown`, and nothing is spent.

    So is an account on its own key, for now: the loop calls the provider
    on the one credential its root built, the platform's, so a call held
    for the tenant's key would run on the platform's and be billed nothing.
    It is refused until the tenant's credential reaches the call."""
    credential = credential_of(account)
    assert account is not None
    if account.funding is FundingMode.OWN_KEY:
        raise SpenderUnknown(
            "the tenant's own key does not reach the call yet; nothing is spent on the platform's"
        )
    plan = plans.get(account.plan)
    if plan is None:
        raise SpenderUnknown(f"the tenant's plan {account.plan_id} is unknown; nothing is spent")
    start, end = billing_period(account.period_anchor, now)
    return Funding(
        mode=account.funding,
        credential=credential,
        plan=plan.ref,
        included_units=plan.included_units,
        unit_price_micros=plan.unit_price_micros,
        micros_per_unit=units.micros_per_unit,
        credit_line_micros=account.credit_line_micros,
        period_start=start,
        period_end=end,
    )


# The unit.


def units_of(cost_micros: int | None, micros_per_unit: int) -> int | None:
    """A reference cost in units, rounded up, so a hold never falls short of
    a figure by its rounding. None when the cost is unknown."""
    if cost_micros is None:
        return None
    return -(-cost_micros // micros_per_unit)


# The counts a hold moves.

CountKey = tuple[str, datetime]
"""A counter and the start of its period."""


def line_keys(line: HoldLine) -> tuple[CountKey, CountKey]:
    """A budget line's two counters in its window: reference cost and native
    tokens."""
    return (
        (f"budget:{line.budget_id}:cost", line.window_start),
        (f"budget:{line.budget_id}:tokens", line.window_start),
    )


def raise_keys(budget_id: UUID, window_start: datetime) -> tuple[CountKey, CountKey]:
    return (
        (f"budget:{budget_id}:cost", window_start),
        (f"budget:{budget_id}:tokens", window_start),
    )


def bucket_key(bucket: Bucket, funding: Funding) -> CountKey:
    """A bucket's counter: the included units and the line of credit each
    billing period, the granted units and the credits for the account's
    life."""
    if bucket in (Bucket.INCLUDED, Bucket.LINE):
        return (f"bucket:{bucket.value}", funding.period_start)
    return (f"bucket:{bucket.value}", EPOCH)


def lifetime_key(bucket: Bucket) -> CountKey:
    return (f"bucket:{bucket.value}", EPOCH)


def hold_keys(hold: FundedHold) -> list[CountKey]:
    """Every counter a hold moves, in the one order the ledger locks them."""
    keys: set[CountKey] = set()
    for line in hold.hold.lines:
        keys.update(line_keys(line))
    if hold.funding.mode is FundingMode.PLATFORM:
        keys.update(bucket_key(bucket, hold.funding) for bucket in BUCKET_ORDER)
    return sorted(keys)


def _count(counts: Mapping[CountKey, Count], key: CountKey) -> Count:
    return counts.get(key) or Count(counter=key[0], start=key[1])


def with_raises(
    lines: Sequence[HoldLine], counts: Mapping[CountKey, Count]
) -> tuple[HoldLine, ...]:
    """Each line's amount with the one-time raise of its window added: a
    raise counts in the window it was made for and in no other."""
    raised = []
    for line in lines:
        cost_key, tokens_key = line_keys(line)
        amount = line.amount
        extra_cost, extra_tokens = _count(counts, cost_key).added, _count(counts, tokens_key).added
        if extra_cost or extra_tokens:
            amount = Amount(
                cost_micros=None if amount.cost_micros is None else amount.cost_micros + extra_cost,
                tokens=None if amount.tokens is None else amount.tokens + extra_tokens,
            )
        raised.append(line.model_copy(update={"amount": amount}))
    return tuple(raised)


def tally_of(line: HoldLine, counts: Mapping[CountKey, Count]) -> Tally:
    """A line's window as the engine's breaches read it."""
    cost, tokens = (_count(counts, key) for key in line_keys(line))
    return Tally(
        budget_id=line.budget_id,
        window_start=line.window_start,
        held_cost_micros=cost.held,
        held_tokens=tokens.held,
        spent_cost_micros=cost.spent,
        spent_tokens=tokens.spent,
    )


# The buckets.


def _cap(bucket: Bucket, funding: Funding, count: Count) -> int:
    match bucket:
        case Bucket.INCLUDED:
            return funding.included_units
        case Bucket.LINE:
            return funding.credit_line_micros
        case Bucket.GRANTED | Bucket.CREDITS:
            return count.added


def available(bucket: Bucket, funding: Funding, count: Count) -> int:
    """What a bucket still holds: its cap less what open holds reserve and
    what was spent. Credits spent past their confirmed sum leave none."""
    return max(0, _cap(bucket, funding, count) - count.held - count.spent)


def draw_of(units: int, funding: Funding, counts: Mapping[CountKey, Count]) -> tuple[Draw, int]:
    """The draw of `units` across the buckets, in the fixed order: each takes
    what it holds, a money bucket in whole units at the plan's price. The
    second figure is what no bucket covers. Prepaid and postpaid differ only
    in which bucket holds room."""
    remaining = units
    taken: dict[str, int] = {}
    for bucket in BUCKET_ORDER:
        room = available(bucket, funding, _count(counts, bucket_key(bucket, funding)))
        if bucket in MONEY_BUCKETS:
            take = min(remaining, room // funding.unit_price_micros)
            taken[bucket.value] = take * funding.unit_price_micros
        else:
            take = min(remaining, room)
            taken[bucket.value] = take
        remaining -= take
    return Draw(**taken), remaining


def shortfall_of(
    units: int, short: int, funding: Funding, counts: Mapping[CountKey, Count]
) -> Shortfall:
    """The shortfall of a hold, and whether a fresh billing period covers it:
    the included units and the line of credit refill, the granted units and
    the credits do not."""
    lasting = sum(
        available(bucket, funding, _count(counts, bucket_key(bucket, funding)))
        // (funding.unit_price_micros if bucket in MONEY_BUCKETS else 1)
        for bucket in (Bucket.GRANTED, Bucket.CREDITS)
    )
    fresh = funding.included_units + funding.credit_line_micros // funding.unit_price_micros
    covered = units <= lasting + fresh
    return Shortfall(units=units, short=short, resets_at=funding.period_end if covered else None)


def open_answer(
    hold: FundedHold, counts: Mapping[CountKey, Count]
) -> tuple[FundedHold, Turned | None]:
    """What the ledger does with a hold under its lock: the hold as it is
    written (its lines with their window's raise, its buckets drawn), or
    every reason it is turned away. A hold on the platform's key whose cost
    is unknown is turned away by a shortfall no period clears."""
    lines = with_raises(hold.hold.lines, counts)
    checked = hold.hold.model_copy(update={"lines": lines})
    tallies = {(line.budget_id, line.window_start): tally_of(line, counts) for line in lines}
    found = breaches(checked, tallies)
    refusal = Refusal(breaches=found) if found else None
    shortfall = None
    draw = NO_DRAW
    if hold.funding.mode is FundingMode.PLATFORM:
        if hold.units is None:
            shortfall = Shortfall(units=None, short=1, resets_at=None)
        else:
            draw, short = draw_of(hold.units, hold.funding, counts)
            if short:
                shortfall = shortfall_of(hold.units, short, hold.funding, counts)
    written = hold.model_copy(update={"hold": checked, "draw": draw})
    if refusal is not None or shortfall is not None:
        return written, Turned(refusal=refusal, shortfall=shortfall)
    return written, None


def opened(hold: FundedHold) -> dict[CountKey, tuple[int, int]]:
    """What an open hold adds to each counter it moves: (held, spent)."""
    moves: dict[CountKey, tuple[int, int]] = {}
    exposure = hold.hold.exposure
    for line in hold.hold.lines:
        cost_key, tokens_key = line_keys(line)
        moves[cost_key] = (exposure.cost_micros or 0, 0)
        moves[tokens_key] = (exposure.tokens, 0)
    if hold.funding.mode is FundingMode.PLATFORM:
        for bucket in BUCKET_ORDER:
            moves[bucket_key(bucket, hold.funding)] = (hold.draw.of(bucket), 0)
    return moves


def closed(
    hold: FundedHold, settlement: Settlement, charge: Charge
) -> dict[CountKey, tuple[int, int]]:
    """What a settlement moves on each counter of its hold: the hold's
    reserve leaves what is held, and what was spent joins what was spent.
    A cost no price gave counts as nothing."""
    moves: dict[CountKey, tuple[int, int]] = {}
    exposure = hold.hold.exposure
    for line in hold.hold.lines:
        cost_key, tokens_key = line_keys(line)
        moves[cost_key] = (-(exposure.cost_micros or 0), settlement.spent.cost_micros or 0)
        moves[tokens_key] = (-exposure.tokens, settlement.spent.tokens)
    if hold.funding.mode is FundingMode.PLATFORM:
        for bucket in BUCKET_ORDER:
            moves[bucket_key(bucket, hold.funding)] = (
                -hold.draw.of(bucket),
                charge.draw.of(bucket),
            )
    return moves


def moved(count: Count, held: int, spent: int) -> Count:
    return count.model_copy(
        update={"held": max(0, count.held + held), "spent": count.spent + spent}
    )


# The charge.


def taken_by(hold: FundedHold, units: int) -> Draw:
    """What a call's spent units take of the buckets: in the fixed order,
    each within what the hold reserved there. Units past the whole hold
    are charged in full to the last money bucket the account has, never
    absorbed."""
    funding = hold.funding
    if funding.mode is not FundingMode.PLATFORM:
        return NO_DRAW
    remaining = units
    taken: dict[str, int] = {}
    for bucket in BUCKET_ORDER:
        reserved = hold.draw.of(bucket)
        if bucket in MONEY_BUCKETS:
            take = min(remaining, reserved // funding.unit_price_micros)
            taken[bucket.value] = take * funding.unit_price_micros
        else:
            take = min(remaining, reserved)
            taken[bucket.value] = take
        remaining -= take
    if remaining:
        last = Bucket.LINE if funding.credit_line_micros else Bucket.CREDITS
        taken[last.value] += remaining * funding.unit_price_micros
    return Draw(**taken)


def charge_of(hold: FundedHold, settlement: Settlement, charge_id: UUID, now: datetime) -> Charge:
    """The bill of one call: its spent reference cost in units, and what
    each bucket paid; what the tenant is billed is what the money buckets
    paid. A call on the tenant's own key draws no bucket and is billed
    nothing here."""
    units = units_of(settlement.spent.cost_micros, hold.funding.micros_per_unit) or 0
    draw = taken_by(hold, units)
    return Charge(
        id=charge_id,
        created_at=now,
        hold_id=hold.id,
        price_version=None if hold.priced is None else hold.priced.version,
        units=units,
        draw=draw,
        amount_micros=draw.charged_micros,
    )


# The anomaly guard.


class AnomalyGuard(Platform):
    factor: int = Field(default=10, ge=2)  # how many times the norm is far above it
    min_calls: int = Field(default=5, ge=1)  # the calls a session makes before it has a norm
    recent: int = Field(default=20, ge=1)  # the calls the norm is read over
    floor_micros: int = Field(default=1_000_000, ge=0)  # below this, no call is an anomaly


def norm_of(costs: Sequence[int]) -> int:
    """A session's norm: the median expected cost of its recent calls."""
    return int(statistics.median(costs))


def far_above(cost: int | None, recent: Sequence[int], guard: AnomalyGuard) -> bool:
    """Whether a call's expected cost is far above its session's norm. A
    session with too few calls has no norm, and a cost under the floor is
    never an anomaly."""
    if cost is None or len(recent) < guard.min_calls or cost <= guard.floor_micros:
        return False
    return cost > guard.factor * norm_of(recent)


# The parks, and what a person is told.


def shortfall_park(shortfall: Shortfall) -> Park:
    """A shortfall parks on the budget: a spend limit. It tries again by
    itself at the next billing period when that covers the call."""
    unlock = PRICE_UNLOCK if shortfall.units is None else FUNDS_UNLOCK
    return Park(reason=ParkReason.BUDGET, unlock=unlock, retry_at=shortfall.resets_at)


def anomaly_park() -> Park:
    return Park(reason=ParkReason.PERSON, unlock=ANOMALY_UNLOCK)


class LimitKind(StrEnum):
    RATE = "rate"  # how fast: the provider's
    SPEND = "spend"  # how much: a budget, or the buckets
    PERSON = "person"  # a person decides
    OTHER = "other"


class Notice(Platform):
    """What a person is told of a parked session."""

    limit: LimitKind
    text: str


def notice_of(park: Park) -> Notice:
    """A park in a person's words. A rate limit and a spend limit are told
    apart, always: the provider's pace is never a budget to top up, and a
    budget is never a provider's pace to wait out."""
    match park.reason:
        case ParkReason.PROVIDER:
            return Notice(
                limit=LimitKind.RATE,
                text=(
                    f"The model provider ({park.unlock}) is limiting calls or failing for now. "
                    "The session tries again on its own; adding credit does not change it."
                ),
            )
        case ParkReason.BUDGET if park.unlock == FUNDS_UNLOCK:
            when = "a person adds credit" if park.retry_at is None else "the next billing period"
            return Notice(
                limit=LimitKind.SPEND,
                text=f"The account's balance does not cover this call. It waits until {when}.",
            )
        case ParkReason.BUDGET if park.unlock == PRICE_UNLOCK:
            return Notice(
                limit=LimitKind.SPEND,
                text="This call has no price to bill it by. It waits until the model is priced.",
            )
        case ParkReason.BUDGET:
            when = "a person raises it" if park.retry_at is None else "its window resets"
            return Notice(
                limit=LimitKind.SPEND,
                text=f"A spending limit is reached. The session waits until {when}.",
            )
        case ParkReason.PERSON if park.unlock == ANOMALY_UNLOCK:
            return Notice(
                limit=LimitKind.PERSON,
                text="This call costs far more than the session's others. It waits for a person.",
            )
        case _:
            return Notice(limit=LimitKind.OTHER, text=f"The session waits: {park.reason.value}.")
