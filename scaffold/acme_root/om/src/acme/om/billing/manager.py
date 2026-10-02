"""The billing swimlane: a tenant's account, its limits' windows, its
buckets, and the one ledger every hold, settlement, and charge posts to.

Opening or changing an account governs what the org's members may spend,
so it takes the permission that governs members, as a budget does; reading
takes READ. A credit is posted only from the payment provider's verified
confirmation, and a top-up never raises a limit. The gate is
`MoneyGateInterface`, beside this one."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.billing.types.account import Account, AccountRequest
from acme.om.billing.types.ledger import Approval, Count, Credit, Grant, WindowRaise
from acme.om.budgets.types.amount import Amount
from acme.om.budgets.types.hold import Tally
from acme.om.context import OperatorContext, TenantContext


class BillingManagerInterface(ABC):
    @abstractmethod
    async def open_account(self, ctx: TenantContext, request: AccountRequest) -> Account:
        """The tenant's account, on the latest version of the plan it names,
        its first billing period starting now, in the zone it names. One an
        org holds already answers as stored. An unknown plan or zone, or an
        own key with no reference, is `ValidationFailed`."""
        ...

    @abstractmethod
    async def get_account(self, ctx: TenantContext) -> Account:
        """The tenant's account; `NotFound` before it opens."""
        ...

    @abstractmethod
    async def set_time_zone(self, ctx: TenantContext, zone: str, expected_version: int) -> Account:
        """The tenant's zone from now on, conditioned on the version the
        caller read (`PreconditionFailed` when it moved). The window open
        now keeps its start and ends at the new zone's first boundary at or
        after its own end: no change of zone opens a window."""
        ...

    @abstractmethod
    async def confirm_payment(
        self, ctx: TenantContext, payload: bytes, signature: str | None
    ) -> Credit:
        """Posts the credit the provider's confirmation carries, once its
        signature checks out (`DeliveryRefused` otherwise, with nothing
        posted). A confirmation of another tenant is `NotAuthorized`. One
        payment credits once: a redelivery answers the first credit. Then
        the sessions of the org parked on a budget are woken, and each asks
        its gate again; no limit changes."""
        ...

    @abstractmethod
    async def grant_units(
        self, ctx: OperatorContext, org_id: UUID, units: int, reason: str
    ) -> Grant:
        """Units the platform grants the tenant, for its life."""
        ...

    @abstractmethod
    async def raise_once(self, ctx: TenantContext, budget_id: UUID, amount: Amount) -> WindowRaise:
        """A one-time raise of a budget for the window open now, and for no
        other: the budget's own amount is unchanged. The sessions parked on
        a budget are woken."""
        ...

    @abstractmethod
    async def approve_call(
        self, ctx: TenantContext, session_id: UUID, up_to_micros: int
    ) -> Approval:
        """A person's yes to the next call of a session past its norm, up to
        a cost; the session parked on it is woken."""
        ...

    @abstractmethod
    async def get_spend(self, ctx: TenantContext, budget_id: UUID) -> Tally:
        """What the budget's current window, as the tenant counts it, spent
        and holds: the one aggregation every view reads, the cap's
        included."""
        ...

    @abstractmethod
    async def get_balances(self, ctx: TenantContext) -> tuple[Count, ...]:
        """Each bucket's count in the current billing period, in the order
        a hold draws them."""
        ...
