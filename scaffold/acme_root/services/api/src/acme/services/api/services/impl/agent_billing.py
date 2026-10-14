from uuid import UUID

from acme.om.billing import BillingManagerInterface
from acme.om.budgets.types.amount import Amount
from acme.om.context import TenantContext
from acme.services.api.services.billing import BillingServiceInterface
from acme.services.api.services.impl.ledgers import entry_view
from acme.services.api.types.billing import CostApprovalRequest, RaiseRequest
from acme.services.api.types.ledgers import LedgerEntryView


class BillingServiceImpl(BillingServiceInterface):
    def __init__(self, billing: BillingManagerInterface) -> None:
        self._billing = billing

    async def approve_call(
        self, ctx: TenantContext, session_id: UUID, body: CostApprovalRequest, approval_id: UUID
    ) -> LedgerEntryView:
        approval = await self._billing.approve_call(
            ctx, session_id, body.up_to_micros, approval_id=approval_id
        )
        return entry_view(approval)

    async def raise_once(
        self, ctx: TenantContext, budget_id: UUID, body: RaiseRequest, raise_id: UUID
    ) -> LedgerEntryView:
        amount = Amount(cost_micros=body.cost_micros, tokens=body.tokens)
        raised = await self._billing.raise_once(ctx, budget_id, amount, raise_id=raise_id)
        return entry_view(raised)

    async def confirm_payment(
        self, ctx: TenantContext, payload: bytes, signature: str | None
    ) -> LedgerEntryView:
        return entry_view(await self._billing.confirm_payment(ctx, payload, signature))
