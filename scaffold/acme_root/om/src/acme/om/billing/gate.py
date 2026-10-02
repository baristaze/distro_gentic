"""The gate the platform puts behind the engine's: one check before every
model call and every job that spends, which holds the call's worst case on
its limits and on the buckets that pay for it, in one ledger.

It is the engine's `BudgetGateInterface`, with what a model call adds: the
row of the price table its cap was read from, which its bill is read from
too."""

from abc import abstractmethod
from uuid import UUID

from acme.om.billing.types.ledger import FundedHold, PricedAt
from acme.om.budgets.gate import BudgetGateInterface
from acme.om.budgets.types.breach import Refusal
from acme.om.budgets.types.hold import HoldRequest
from acme.om.context import TenantContext


class MoneyGateInterface(BudgetGateInterface):
    @abstractmethod
    async def authorize_priced(
        self, ctx: TenantContext, request: HoldRequest, priced: PricedAt | None
    ) -> FundedHold | Refusal:
        """`authorize`, for a call priced from the row `priced` names. Who
        pays is read first: an account that cannot say is `SpenderUnknown`,
        and nothing is held or spent. A call far above its session's norm
        pages the operator and is `GateParked` for a person; a call no
        bucket covers is `GateParked` on the budget. Either way nothing is
        held. A refusal lists every limit it breaches."""
        ...

    @abstractmethod
    async def read_hold(self, ctx: TenantContext, hold_id: UUID) -> FundedHold:
        """A hold of the tenant; one another tenant holds is `NotFound`."""
        ...
