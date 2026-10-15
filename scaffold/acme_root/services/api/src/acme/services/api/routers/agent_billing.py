"""The tenant's writes that clear a park on its money, each held to the
permission agent billing checks, each waking the sessions parked on it, and each
answering the ledger entry it posted:

- a call far above its session's norm, approved up to a cost, by a person
  who approves such calls (`manage_members`);
- a budget raised for the window open now, and no other, by a person who
  sets budgets (`manage_members`);
- a payment the provider confirmed, posted with the provider's signature
  by a person who may write; the signature is checked before anything is
  credited, and a confirmation of another tenant is refused.

Each takes an Idempotency-Key, so a retried approval or raise posts once;
a payment credits once by the provider's own reference too.

The operators' read of a tenant's ledger under /v1/admin: its entries,
the newest first, of one kind, one hold, or one session when asked, and
whether the read was cut at its limit. It takes `OperatorContext` and the
read permission, names the tenant, and is logged with the tenant and the
operator; a tenant's credential never reaches it. An operator who may
write grants the tenant units for its life, under an Idempotency-Key, so a
retry grants once, and the tenant's sessions parked on its funds wake."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.om.agent_billing.types.spend_ledger import EntryKind
from acme.services.api.gateway.admin import OperatorCtx
from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem, OperatorIdem
from acme.services.api.gateway.payments import PaymentDelivery
from acme.services.api.gateway.platform_resolve import AgentBillingService, SpendLedgersService
from acme.services.api.types.agent_billing import (
    CostApprovalRequest,
    RaiseRequest,
    SpendLedgerEntryView,
    SpendLedgerPageView,
    SpendUnitsGrantRequest,
)
from acme.services.api.types.common import LIMIT_DEFAULT

router = APIRouter(tags=["agent_billing"])


operator = APIRouter(prefix="/admin", tags=["agent_billing"])


@router.post(
    "/agent-sessions/{agent_session_id}/cost-approval",
    response_model=SpendLedgerEntryView,
    status_code=201,
)
async def approve_call(
    ctx: Ctx,
    agent_billing: AgentBillingService,
    agent_session_id: UUID,
    body: CostApprovalRequest,
    idem: Idem,
) -> Response:
    """The session's next call past its norm, let through up to the cost
    named; the session parked on it runs again."""
    return await idem.run(
        201,
        lambda attempt: agent_billing.approve_call(ctx, agent_session_id, body, attempt.target_id),
    )


@router.post(
    "/budgets/{spend_budget_id}/raises", response_model=SpendLedgerEntryView, status_code=201
)
async def raise_once(
    ctx: Ctx,
    agent_billing: AgentBillingService,
    spend_budget_id: UUID,
    body: RaiseRequest,
    idem: Idem,
) -> Response:
    """The budget raised for the window open now; its own amount is
    unchanged. The sessions parked on a budget run again."""
    return await idem.run(
        201, lambda attempt: agent_billing.raise_once(ctx, spend_budget_id, body, attempt.target_id)
    )


@router.post("/agent-billing/payments", response_model=SpendLedgerEntryView, status_code=201)
async def confirm_payment(
    ctx: Ctx, agent_billing: AgentBillingService, delivery: PaymentDelivery, idem: Idem
) -> Response:
    """The credit of a payment the provider confirmed: the body is the
    provider's confirmation, byte for byte, and `Payment-Signature` its
    signature. `webhook_signature_invalid` when the signature does not
    check out, and nothing is credited."""
    return await idem.run(
        201,
        lambda _attempt: agent_billing.confirm_payment(ctx, delivery.payload, delivery.signature),
    )


@operator.get("/orgs/{org_id}/spend-ledger", response_model=SpendLedgerPageView)
async def get_ledger(
    admin: OperatorCtx,
    service: SpendLedgersService,
    org_id: UUID,
    kind: EntryKind | None = None,
    spend_hold_id: UUID | None = None,
    agent_session_id: UUID | None = None,
    limit: int = LIMIT_DEFAULT,
) -> SpendLedgerPageView:
    """The tenant's entries, the newest first, narrowed to one kind, one
    hold (its hold, settlement, and charge), or one session (its holds and
    approvals) when named. `has_more` says the read was cut at its limit."""
    return await service.get_entries(
        admin,
        org_id,
        kind=kind,
        spend_hold_id=spend_hold_id,
        agent_session_id=agent_session_id,
        limit=limit,
    )


@operator.post("/orgs/{org_id}/grants", response_model=SpendLedgerEntryView, status_code=201)
async def grant_units(
    admin: OperatorCtx,
    service: SpendLedgersService,
    org_id: UUID,
    body: SpendUnitsGrantRequest,
    idem: OperatorIdem,
) -> Response:
    """Units granted the tenant for its life, and why; its sessions parked
    on its funds run again. An org that is gone is `404`."""
    return await idem.run(
        201, lambda attempt: service.grant_units(admin, org_id, body, attempt.target_id)
    )
