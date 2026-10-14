from uuid import UUID

from acme.om.agent_billing import AgentBillingManagerInterface
from acme.om.budgets.types.amount import Amount
from acme.om.context import TenantContext
from acme.services.api.services.agent_billing import AgentBillingServiceInterface
from acme.services.api.services.impl.spend_ledgers import entry_view
from acme.services.api.types.agent_billing import CostApprovalRequest, RaiseRequest
from acme.services.api.types.spend_ledgers import SpendLedgerEntryView


class AgentBillingServiceImpl(AgentBillingServiceInterface):
    def __init__(self, agent_billing: AgentBillingManagerInterface) -> None:
        self._agent_billing = agent_billing

    async def approve_call(
        self, ctx: TenantContext, session_id: UUID, body: CostApprovalRequest, approval_id: UUID
    ) -> SpendLedgerEntryView:
        approval = await self._agent_billing.approve_call(
            ctx, session_id, body.up_to_micros, approval_id=approval_id
        )
        return entry_view(approval)

    async def raise_once(
        self, ctx: TenantContext, budget_id: UUID, body: RaiseRequest, raise_id: UUID
    ) -> SpendLedgerEntryView:
        amount = Amount(cost_micros=body.cost_micros, tokens=body.tokens)
        raised = await self._agent_billing.raise_once(ctx, budget_id, amount, raise_id=raise_id)
        return entry_view(raised)

    async def confirm_payment(
        self, ctx: TenantContext, payload: bytes, signature: str | None
    ) -> SpendLedgerEntryView:
        return entry_view(await self._agent_billing.confirm_payment(ctx, payload, signature))
