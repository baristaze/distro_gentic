"""The one ledger: every hold, settlement, and charge, every confirmed
credit and granted unit, every one-time raise, and every approval a person
gives a call past its session's norm, as entries written once.

A hold carries what the gate read: the account's funding as it stood, the
price version the cap was read at, and the call's worst case in units. The
ledger then draws the buckets on the hold alone, under the lock of their
counts, so it never reads the account. A settlement and its charge are
written together, once per hold; the charge is priced from the hold's own
version, so a cap and a bill read the same price."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from acme.om.base import Created, Identifiable, Platform
from acme.om.billing.types.account import FundingMode
from acme.om.billing.types.plan import MAX_NAME, PlanRef
from acme.om.budgets.types.breach import Refusal
from acme.om.budgets.types.hold import Hold, Settlement


class Bucket(StrEnum):
    """What pays for a call on the platform's key, drawn in this order."""

    INCLUDED = "included"  # the plan's units, each billing period
    GRANTED = "granted"  # units the platform granted
    CREDITS = "credits"  # prepaid credits, in millionths, once confirmed
    LINE = "line"  # an enterprise line of credit, in millionths, each billing period


BUCKET_ORDER: tuple[Bucket, ...] = (Bucket.INCLUDED, Bucket.GRANTED, Bucket.CREDITS, Bucket.LINE)
"""The fixed order a hold draws in, whoever the tenant is."""

MONEY_BUCKETS = frozenset({Bucket.CREDITS, Bucket.LINE})
"""The buckets counted in millionths; the others count units."""


class Funding(Platform):
    """The account as the gate read it for one hold."""

    mode: FundingMode
    credential: str = Field(min_length=1, max_length=MAX_NAME)
    plan: PlanRef
    included_units: int = Field(ge=0)
    unit_price_micros: int = Field(ge=1)
    micros_per_unit: int = Field(ge=1)
    credit_line_micros: int = Field(ge=0)
    period_start: datetime
    period_end: datetime


class PricedAt(Platform):
    """The row of the price table a model call's cap was read from."""

    version: str = Field(min_length=1, max_length=MAX_NAME)
    provider: str = Field(min_length=1, max_length=MAX_NAME)
    model: str = Field(min_length=1, max_length=MAX_NAME)


class Draw(Platform):
    """What a hold reserves, or a settlement takes, of each bucket: units of
    the included and granted ones, millionths of the money ones."""

    included: int = Field(default=0, ge=0)
    granted: int = Field(default=0, ge=0)
    credits: int = Field(default=0, ge=0)
    line: int = Field(default=0, ge=0)

    def of(self, bucket: Bucket) -> int:
        return int(getattr(self, bucket.value))

    @property
    def charged_micros(self) -> int:
        """What the tenant is billed for it: the money buckets alone."""
        return self.credits + self.line


NO_DRAW = Draw()


class FundedHold(Platform):
    """The engine's hold, and what billing reads beside it. It is the hold's
    entry in the ledger, under the hold's own id."""

    hold: Hold
    funding: Funding
    units: int | None = Field(ge=0)  # the worst case in units; None when its cost is unknown
    priced: PricedAt | None = None  # None for a job, which no price table prices
    draw: Draw = NO_DRAW  # filled by the ledger under its lock
    approval_id: UUID | None = None  # the approval that let it past its session's norm

    @property
    def id(self) -> UUID:
        return self.hold.id

    @property
    def created_at(self) -> datetime:
        return self.hold.created_at

    @property
    def session_id(self) -> UUID | None:
        return self.hold.session_id


class Charge(Identifiable, Created):
    """What one call is billed: its units, what each bucket paid, and the
    sum the money buckets paid. Written with its settlement."""

    hold_id: UUID
    price_version: str | None = Field(default=None, max_length=MAX_NAME)
    units: int = Field(ge=0)
    draw: Draw
    amount_micros: int = Field(ge=0)


class Credit(Identifiable, Created):
    """Prepaid credit, posted only from the provider's verified confirmation,
    once per payment reference."""

    reference: str = Field(min_length=1, max_length=MAX_NAME)
    amount_micros: int = Field(gt=0)
    confirmed_at: datetime


class Grant(Identifiable, Created):
    """Units the platform granted a tenant."""

    units: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=MAX_NAME)
    granted_by: UUID


class WindowRaise(Identifiable, Created):
    """A one-time raise of one budget for the window open when it was made,
    and for no other."""

    budget_id: UUID
    window_start: datetime
    cost_micros: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    raised_by: UUID


class Approval(Identifiable, Created):
    """A person's yes to one call of a session past its norm, up to a cost."""

    session_id: UUID
    up_to_micros: int = Field(gt=0)
    approved_by: UUID


Entry = FundedHold | Settlement | Charge | Credit | Grant | WindowRaise | Approval
"""One entry of the ledger, of whichever kind."""


class EntryPage(Platform):
    """One read of a tenant's ledger, the newest first. `has_more` says the
    read was cut at its limit: older entries match it too. The manager asks
    storage for one entry more than the limit and keeps it out, so it is a
    fact about the entries and not a guess about the count."""

    items: tuple[Entry, ...]
    has_more: bool


class EntryKind(StrEnum):
    HOLD = "hold"
    SETTLEMENT = "settlement"
    CHARGE = "charge"
    CREDIT = "credit"
    GRANT = "grant"
    RAISE = "raise"
    APPROVAL = "approval"


class Count(Platform):
    """One counter in one period: what open holds reserve, what was spent,
    and what was added to it (credits, grants, a raise). A ledger's counts
    can be rebuilt from its entries."""

    counter: str = Field(min_length=1, max_length=MAX_NAME)
    start: datetime
    held: int = Field(default=0, ge=0)
    spent: int = Field(default=0, ge=0)
    added: int = Field(default=0, ge=0)


class Shortfall(Platform):
    """Units of a call's worst case no bucket covers. `units` is None when
    the call's cost is unknown, so no bucket can be drawn for it.
    `resets_at` is when a fresh billing period covers it, or None when only
    a person can: a top-up, a grant, a plan with room, or a price."""

    units: int | None = Field(ge=0)
    short: int = Field(ge=1)
    resets_at: datetime | None
    reserved: int = Field(default=0, ge=0)
    """Units the buckets' open holds reserve: when they cover the shortfall,
    their settlements can free the room."""


class Turned(Platform):
    """What the ledger answers a hold it does not open: the budget lines it
    breaches, the units no bucket covers, or both. Nothing is written."""

    refusal: Refusal | None = None
    shortfall: Shortfall | None = None
