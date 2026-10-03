"""The operators' read of a tenant's ledger under /v1/admin: its entries,
the newest first, of one kind, one hold, or one session when asked, and
whether the read was cut at its limit. It takes `OperatorContext` and the
read permission, names the tenant, and is logged with the tenant and the
operator; a tenant's credential never reaches it."""

from uuid import UUID

from fastapi import APIRouter

from acme.om.billing.types.ledger import EntryKind
from acme.services.api.gateway.admin import OperatorCtx
from acme.services.api.gateway.resolve import LedgersService
from acme.services.api.types.common import LIMIT_DEFAULT
from acme.services.api.types.ledgers import LedgerPageView

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/orgs/{org_id}/ledger", response_model=LedgerPageView)
async def get_ledger(
    admin: OperatorCtx,
    service: LedgersService,
    org_id: UUID,
    kind: EntryKind | None = None,
    hold_id: UUID | None = None,
    session_id: UUID | None = None,
    limit: int = LIMIT_DEFAULT,
) -> LedgerPageView:
    """The tenant's entries, the newest first, narrowed to one kind, one
    hold (its hold, settlement, and charge), or one session (its holds and
    approvals) when named. `has_more` says the read was cut at its limit."""
    return await service.get_entries(
        admin, org_id, kind=kind, hold_id=hold_id, session_id=session_id, limit=limit
    )
