"""The money ledger contract: a hold is held on its limits and drawn on its
buckets in the fixed order, or turned away with nothing written; holds
over one bucket never all pass when fewer fit; a hold closes once, its
settlement and charge together; a payment credits once; a raise counts in
its window alone; and every entry of a call is in the one ledger. The
cases named in `CROSS_TENANT_CASES` are the tenant fence's evidence."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.billing.rules import bucket_key, charge_of, line_keys
from acme.om.billing.storage import MoneyLedgerStorageInterface
from acme.om.billing.types.account import FundingMode
from acme.om.billing.types.ledger import (
    Approval,
    Bucket,
    Charge,
    Credit,
    EntryKind,
    FundedHold,
    Funding,
    Grant,
    PricedAt,
    Turned,
    WindowRaise,
)
from acme.om.billing.types.plan import PlanRef
from acme.om.budgets.rules import settlement_of
from acme.om.budgets.types.amount import Spend
from acme.om.budgets.types.hold import Billed, BillUnknown, Hold, HoldLine, Settlement
from acme.om.exceptions import NotFound, TenantMismatch
from contracts.ledger_storage import a_line
from contracts.racing import race

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "close_hold",
        "count_tenant",
        "open_hold",
        "post_approval",
        "post_credit",
        "post_grant",
        "post_raise",
        "read_counts",
        "read_entries",
        "read_hold",
    }
)
"""Every method of `MoneyLedgerStorageInterface` that takes a tenant has a
case in this module that presents another tenant's."""

PERIOD = datetime(2026, 10, 1, tzinfo=UTC)


def funding(
    *,
    included: int = 0,
    line: int = 0,
    price: int = 1_000,
    mode: FundingMode = FundingMode.PLATFORM,
) -> Funding:
    return Funding(
        mode=mode,
        credential="platform" if mode is FundingMode.PLATFORM else "tenant-key-1",
        plan=PlanRef(id="test", version=1),
        included_units=included,
        unit_price_micros=price,
        micros_per_unit=1_000,
        credit_line_micros=line,
        period_start=PERIOD,
        period_end=PERIOD + timedelta(days=31),
    )


def a_funded_hold(
    *lines: HoldLine,
    units: int | None = 5,
    paid_by: Funding | None = None,
    session_id: UUID | None = None,
) -> FundedHold:
    return FundedHold(
        hold=Hold(
            id=new_id(),
            created_at=utcnow(),
            spender_id=new_id(),
            session_id=session_id or new_id(),
            purpose="main",
            exposure=Spend(cost_micros=None if units is None else units * 1_000, tokens=100),
            lines=lines,
        ),
        funding=paid_by or funding(included=10),
        units=units,
        priced=PricedAt(version="v1", provider="anthropic", model="m"),
    )


def a_credit(amount: int = 5_000, reference: str | None = None) -> Credit:
    return Credit(
        id=new_id(),
        created_at=utcnow(),
        reference=reference or f"pay_{new_id().hex[:8]}",
        amount_micros=amount,
        confirmed_at=utcnow(),
    )


def closing(hold: FundedHold, spent_units: int) -> tuple[Settlement, Charge]:
    now = utcnow()
    bill = Billed(usage=Spend(cost_micros=spent_units * 1_000, tokens=40))
    settlement = settlement_of(hold.hold, bill, new_id(), now)
    return settlement, charge_of(hold, settlement, new_id(), now)


class MoneyLedgerStorageContract:
    @pytest.fixture
    def storage(self) -> MoneyLedgerStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_a_hold_is_drawn_in_the_fixed_order_and_moves_its_counts(
        self, storage: MoneyLedgerStorageInterface
    ) -> None:
        org = new_id()
        paid_by = funding(included=2, line=10_000)
        await storage.post_grant(
            org, Grant(id=new_id(), created_at=utcnow(), units=1, reason="t", granted_by=new_id())
        )
        await storage.post_credit(org, a_credit(1_000))
        line = a_line(cost_micros=100_000)
        hold = a_funded_hold(line, units=6, paid_by=paid_by)

        stored = await storage.open_hold(org, hold)

        assert isinstance(stored, FundedHold)
        assert (stored.draw.included, stored.draw.granted) == (2, 1)
        assert (stored.draw.credits, stored.draw.line) == (1_000, 2_000)
        assert await storage.read_hold(org, hold.id) == stored
        keys = [bucket_key(bucket, paid_by) for bucket in Bucket] + list(line_keys(line))
        counts = await storage.read_counts(org, keys)
        held = [counts[key].held for key in keys]
        assert held == [2, 1, 1_000, 2_000, 6_000, 100]
        assert await storage.open_hold(org, hold) == stored, "a hold opened already is as stored"

    async def test_a_hold_turned_away_writes_nothing_and_says_every_reason(
        self, storage: MoneyLedgerStorageInterface
    ) -> None:
        org = new_id()
        line = a_line(cost_micros=1_000)
        hold = a_funded_hold(line, units=3, paid_by=funding(included=1))

        turned = await storage.open_hold(org, hold)

        assert isinstance(turned, Turned)
        assert turned.refusal is not None and turned.refusal.breaches[0].budget_id == line.budget_id
        assert turned.shortfall is not None and turned.shortfall.short == 2
        assert turned.shortfall.resets_at is None, "a period's one unit never covers three"
        assert await storage.read_hold(org, hold.id) is None
        assert await storage.read_entries(org, limit=10) == []
        assert await storage.read_counts(org, list(line_keys(line))) == {}

    async def test_a_cost_no_price_gives_is_never_drawn(
        self, storage: MoneyLedgerStorageInterface
    ) -> None:
        org = new_id()
        turned = await storage.open_hold(org, a_funded_hold(units=None))
        assert isinstance(turned, Turned) and turned.shortfall is not None
        assert turned.shortfall.units is None and turned.shortfall.resets_at is None

    async def test_an_own_key_draws_no_bucket_and_is_billed_nothing(
        self, storage: MoneyLedgerStorageInterface
    ) -> None:
        org = new_id()
        hold = a_funded_hold(units=7, paid_by=funding(mode=FundingMode.OWN_KEY))
        stored = await storage.open_hold(org, hold)
        assert isinstance(stored, FundedHold) and stored.draw.charged_micros == 0
        settlement, charge = closing(stored, 7)
        _, stored_charge = await storage.close_hold(org, settlement, charge)
        assert stored_charge.units == 7 and stored_charge.amount_micros == 0

    async def test_holds_over_one_bucket_never_all_pass_when_fewer_fit(
        self, storage: MoneyLedgerStorageInterface
    ) -> None:
        org = new_id()
        await storage.post_credit(org, a_credit(3_000))
        paid_by = funding()

        async def one() -> FundedHold | None:
            answer = await storage.open_hold(org, a_funded_hold(units=1, paid_by=paid_by))
            return answer if isinstance(answer, FundedHold) else None

        run = await race(*(one() for _ in range(6)))
        assert len(run.admitted) == 3, run.summary()
        counts = await storage.read_counts(org, [bucket_key(Bucket.CREDITS, paid_by)])
        assert counts[bucket_key(Bucket.CREDITS, paid_by)].held == 3_000

    async def test_a_hold_closes_once_with_its_charge_in_the_one_ledger(
        self, storage: MoneyLedgerStorageInterface
    ) -> None:
        org = new_id()
        line = a_line(cost_micros=100_000)
        paid_by = funding(included=10)
        stored = await storage.open_hold(org, a_funded_hold(line, units=5, paid_by=paid_by))
        assert isinstance(stored, FundedHold)
        settlement, charge = closing(stored, 3)

        first = await storage.close_hold(org, settlement, charge)
        second = await storage.close_hold(org, *closing(stored, 5))

        assert first == (settlement, charge) and second == first, "the first counts"
        kinds = {
            type(e).__name__ for e in await storage.read_entries(org, hold_id=stored.id, limit=10)
        }
        assert kinds == {"FundedHold", "Settlement", "Charge"}
        key = bucket_key(Bucket.INCLUDED, paid_by)
        included = (await storage.read_counts(org, [key]))[key]
        assert (included.held, included.spent) == (0, 3)
        cost = (await storage.read_counts(org, [line_keys(line)[0]]))[line_keys(line)[0]]
        assert (cost.held, cost.spent) == (0, 3_000)

    async def test_read_open_answers_the_slices_unsettled_holds_oldest_first(
        self, storage: MoneyLedgerStorageInterface
    ) -> None:
        """The sweep's read across tenants: every hold opened in the slice
        that no settlement closed, each with its tenant, oldest first, a batch
        at most; never one settled, nor one opened outside the slice."""
        first, second, now = new_id(), new_id(), utcnow()

        def opened(at: datetime) -> FundedHold:
            funded = a_funded_hold(a_line(cost_micros=100_000), paid_by=funding(included=100))
            return funded.model_copy(
                update={"hold": funded.hold.model_copy(update={"created_at": at})}
            )

        old, older, settled = (opened(now - timedelta(hours=h)) for h in (2, 3, 4))
        recent, ancient = opened(now - timedelta(minutes=5)), opened(now - timedelta(days=2))
        for org, hold in (
            (first, old),
            (second, older),
            (first, settled),
            (first, recent),
            (second, ancient),
        ):
            assert isinstance(await storage.open_hold(org, hold), FundedHold)
        await storage.close_hold(first, *closing(settled, 3))
        floor, cut = now - timedelta(days=1), now - timedelta(hours=1)
        found = await storage.read_open(floor, cut, 10)
        assert [(org, hold.id) for org, hold in found] == [(second, older.id), (first, old.id)]
        assert found[0][1] == older.hold
        assert [hold.id for _, hold in await storage.read_open(floor, cut, 1)] == [older.id]

    async def test_a_spend_past_its_hold_is_charged_in_full(
        self, storage: MoneyLedgerStorageInterface
    ) -> None:
        org = new_id()
        stored = await storage.open_hold(org, a_funded_hold(units=2, paid_by=funding(included=2)))
        assert isinstance(stored, FundedHold)
        _, charge = await storage.close_hold(org, *closing(stored, 5))
        assert charge.draw.included == 2 and charge.draw.credits == 3_000
        assert charge.amount_micros == 3_000

    async def test_a_hold_whose_usage_is_unknown_is_charged_whole(
        self, storage: MoneyLedgerStorageInterface
    ) -> None:
        org = new_id()
        stored = await storage.open_hold(org, a_funded_hold(units=4, paid_by=funding(included=9)))
        assert isinstance(stored, FundedHold)
        now = utcnow()
        settlement = settlement_of(stored.hold, BillUnknown(), new_id(), now)
        _, charge = await storage.close_hold(
            org, settlement, charge_of(stored, settlement, new_id(), now)
        )
        assert charge.units == 4

    async def test_a_payment_credits_once(self, storage: MoneyLedgerStorageInterface) -> None:
        org = new_id()
        credit = a_credit(2_500, reference="pay_once")
        first = await storage.post_credit(org, credit)
        again = await storage.post_credit(org, a_credit(2_500, reference="pay_once"))
        assert again == first == credit
        key = bucket_key(Bucket.CREDITS, funding())
        assert (await storage.read_counts(org, [key]))[key].added == 2_500

    async def test_a_raise_counts_in_its_window_alone(
        self, storage: MoneyLedgerStorageInterface
    ) -> None:
        org = new_id()
        line = a_line(cost_micros=1_000)
        later = line.model_copy(update={"window_start": line.window_start + timedelta(days=1)})
        raised = WindowRaise(
            id=new_id(),
            created_at=utcnow(),
            budget_id=line.budget_id,
            window_start=line.window_start,
            cost_micros=4_000,
            raised_by=new_id(),
        )
        assert await storage.post_raise(org, raised) == raised
        assert await storage.post_raise(org, raised) == raised
        assert isinstance(await storage.open_hold(org, a_funded_hold(line, units=4)), FundedHold)
        turned = await storage.open_hold(org, a_funded_hold(later, units=4))
        assert isinstance(turned, Turned) and turned.refusal is not None

    async def test_an_entry_is_written_once_and_read_newest_first(
        self, storage: MoneyLedgerStorageInterface
    ) -> None:
        org = new_id()
        session_id = new_id()
        approval = Approval(
            id=new_id(),
            created_at=utcnow(),
            session_id=session_id,
            up_to_micros=9,
            approved_by=new_id(),
        )
        assert await storage.post_approval(org, approval) == approval
        assert await storage.post_approval(org, approval) == approval
        hold = await storage.open_hold(org, a_funded_hold(session_id=session_id))
        found = await storage.read_entries(org, session_id=session_id, limit=10)
        assert found == [hold, approval]
        assert await storage.read_entries(org, kind=EntryKind.APPROVAL, limit=10) == [approval]

    async def test_another_tenants_ledger_is_never_reached(
        self, storage: MoneyLedgerStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        await storage.post_credit(org, a_credit(5_000, reference="pay_x"))
        hold = await storage.open_hold(org, a_funded_hold(units=1, paid_by=funding()))
        assert isinstance(hold, FundedHold)

        # Paid by the tenant's own key there too, so the hold fits, and its id
        # is what turns it away.
        own = hold.model_copy(update={"funding": funding(mode=FundingMode.OWN_KEY)})
        with pytest.raises(TenantMismatch):
            await storage.open_hold(other, own)
        assert await storage.read_hold(other, hold.id) is None
        with pytest.raises(NotFound):
            await storage.close_hold(other, *closing(hold, 1))
        assert await storage.read_entries(other, limit=10) == []
        key = bucket_key(Bucket.CREDITS, funding())
        assert await storage.read_counts(other, [key]) == {}
        theirs = await storage.post_credit(other, a_credit(1_000, reference="pay_x"))
        assert theirs.amount_micros == 1_000, "a reference is the tenant's own"
        grant = Grant(id=new_id(), created_at=utcnow(), units=1, reason="t", granted_by=new_id())
        await storage.post_grant(org, grant)
        with pytest.raises(TenantMismatch):
            await storage.post_grant(other, grant)
        raised = WindowRaise(
            id=new_id(),
            created_at=utcnow(),
            budget_id=new_id(),
            window_start=PERIOD,
            raised_by=new_id(),
        )
        await storage.post_raise(org, raised)
        with pytest.raises(TenantMismatch):
            await storage.post_raise(other, raised)
        approval = Approval(
            id=new_id(),
            created_at=utcnow(),
            session_id=new_id(),
            up_to_micros=1,
            approved_by=new_id(),
        )
        await storage.post_approval(org, approval)
        with pytest.raises(TenantMismatch):
            await storage.post_approval(other, approval)

    async def test_count_tenant_counts_the_tenants_entries_and_counts_up_to_its_limit(
        self, storage: MoneyLedgerStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        assert await storage.count_tenant(org, 10) == 0
        await storage.post_credit(org, a_credit(5_000, reference="pay_c"))
        # The credit is one entry, and it moves one count.
        assert await storage.count_tenant(org, 10) == 2
        assert await storage.count_tenant(org, 1) == 1
        assert await storage.count_tenant(other, 10) == 0
