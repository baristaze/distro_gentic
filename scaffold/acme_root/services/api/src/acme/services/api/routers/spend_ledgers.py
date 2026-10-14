"""The operators' read of a tenant's ledger under /v1/admin: its entries,
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
from acme.services.api.gateway.idempotency import OperatorIdem
from acme.services.api.gateway.platform_resolve import SpendLedgersService
from acme.services.api.types.common import LIMIT_DEFAULT
from acme.services.api.types.spend_ledgers import (
    SpendLedgerEntryView,
    SpendLedgerPageView,
    SpendUnitsGrantRequest,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/orgs/{org_id}/spend-ledger", response_model=SpendLedgerPageView)
async def get_ledger(
    admin: OperatorCtx,
    service: SpendLedgersService,
    org_id: UUID,
    kind: EntryKind | None = None,
    hold_id: UUID | None = None,
    session_id: UUID | None = None,
    limit: int = LIMIT_DEFAULT,
) -> SpendLedgerPageView:
    """The tenant's entries, the newest first, narrowed to one kind, one
    hold (its hold, settlement, and charge), or one session (its holds and
    approvals) when named. `has_more` says the read was cut at its limit."""
    return await service.get_entries(
        admin, org_id, kind=kind, hold_id=hold_id, session_id=session_id, limit=limit
    )


@router.post("/orgs/{org_id}/grants", response_model=SpendLedgerEntryView, status_code=201)
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
