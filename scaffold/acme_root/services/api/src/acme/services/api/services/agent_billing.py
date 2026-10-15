"""The agent billing service: the tenant's own writes that clear a park on its
money. A person who approves calls past their norm approves one, one who
sets budgets raises a budget for its window, and one who may write posts a
payment the provider confirmed. Each wakes the sessions parked on it and
answers the ledger entry it posted."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.agent_billing import CostApprovalRequest, RaiseRequest
from acme.services.api.types.spend_ledgers import SpendLedgerEntryView


class AgentBillingServiceInterface(ABC):
    @abstractmethod
    async def approve_call(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        body: CostApprovalRequest,
        approval_id: UUID,
    ) -> SpendLedgerEntryView:
        """The approval of the session's next call past its norm, up to the
        cost the body names, posted under `approval_id` once; the session
        parked on it wakes."""
        ...

    @abstractmethod
    async def raise_once(
        self, ctx: TenantContext, spend_budget_id: UUID, body: RaiseRequest, raise_id: UUID
    ) -> SpendLedgerEntryView:
        """The budget raised for the window open now, under `raise_id` once;
        the sessions parked on a budget wake."""
        ...

    @abstractmethod
    async def confirm_payment(
        self, ctx: TenantContext, payload: bytes, signature: str | None
    ) -> SpendLedgerEntryView:
        """The credit the provider's signed confirmation carries, once its
        signature checks out (`DeliveryRefused` otherwise); a redelivery
        answers the first credit. The sessions parked on a budget wake."""
        ...
