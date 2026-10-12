"""The tenant's writes that clear a park on its money, each held to the
permission billing checks, each waking the sessions parked on it, and each
answering the ledger entry it posted:

- a call far above its session's norm, approved up to a cost, by a person
  who approves such calls (`manage_members`);
- a budget raised for the window open now, and no other, by a person who
  sets budgets (`manage_members`);
- a payment the provider confirmed, posted with the provider's signature
  by a person who may write; the signature is checked before anything is
  credited, and a confirmation of another tenant is refused.

Each takes an Idempotency-Key, so a retried approval or raise posts once;
a payment credits once by the provider's own reference too."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.payments import PaymentDelivery
from acme.services.api.gateway.resolve import BillingService
from acme.services.api.types.billing import CostApprovalRequest, RaiseRequest
from acme.services.api.types.ledgers import LedgerEntryView

router = APIRouter(tags=["billing"])


@router.post(
    "/agent-sessions/{session_id}/cost-approval", response_model=LedgerEntryView, status_code=201
)
async def approve_call(
    ctx: Ctx, billing: BillingService, session_id: UUID, body: CostApprovalRequest, idem: Idem
) -> Response:
    """The session's next call past its norm, let through up to the cost
    named; the session parked on it runs again."""
    return await idem.run(
        201, lambda attempt: billing.approve_call(ctx, session_id, body, attempt.target_id)
    )


@router.post("/budgets/{budget_id}/raises", response_model=LedgerEntryView, status_code=201)
async def raise_once(
    ctx: Ctx, billing: BillingService, budget_id: UUID, body: RaiseRequest, idem: Idem
) -> Response:
    """The budget raised for the window open now; its own amount is
    unchanged. The sessions parked on a budget run again."""
    return await idem.run(
        201, lambda attempt: billing.raise_once(ctx, budget_id, body, attempt.target_id)
    )


@router.post("/billing/payments", response_model=LedgerEntryView, status_code=201)
async def confirm_payment(
    ctx: Ctx, billing: BillingService, delivery: PaymentDelivery, idem: Idem
) -> Response:
    """The credit of a payment the provider confirmed: the body is the
    provider's confirmation, byte for byte, and `Payment-Signature` its
    signature. `webhook_signature_invalid` when the signature does not
    check out, and nothing is credited."""
    return await idem.run(
        201, lambda _attempt: billing.confirm_payment(ctx, delivery.payload, delivery.signature)
    )
