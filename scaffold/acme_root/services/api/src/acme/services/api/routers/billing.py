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

An approval and a raise take an Idempotency-Key, so a retry posts once; a
payment credits once by the provider's own reference."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.resolve import BillingService
from acme.services.api.types.billing import CostApprovalRequest, RaiseRequest
from acme.services.api.types.ledgers import LedgerEntryView

PAYMENT_SIGNATURE = "Payment-Signature"
"""The header that carries the payment provider's signature over the body."""

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
    ctx: Ctx,
    billing: BillingService,
    request: Request,
    signature: Annotated[str | None, Header(alias=PAYMENT_SIGNATURE)] = None,
) -> LedgerEntryView:
    """The credit of a payment the provider confirmed: the body is the
    provider's confirmation, byte for byte, and `Payment-Signature` its
    signature. `delivery_refused` when the signature does not check out."""
    return await billing.confirm_payment(ctx, await request.body(), signature)
