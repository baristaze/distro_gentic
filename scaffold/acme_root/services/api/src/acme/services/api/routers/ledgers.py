"""The operators' read of a tenant's ledger under /v1/admin: its entries,
the newest first, of one kind when asked. It takes `OperatorContext` and
the read permission, names the tenant, and is logged with the tenant and
the operator; a tenant's credential never reaches it."""

from uuid import UUID

from fastapi import APIRouter

from acme.om.billing.types.ledger import EntryKind
from acme.services.api.gateway.admin import OperatorCtx
from acme.services.api.gateway.resolve import LedgersService
from acme.services.api.types.common import LIMIT_DEFAULT
from acme.services.api.types.ledgers import LedgerEntryView

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/orgs/{org_id}/ledger", response_model=list[LedgerEntryView])
async def get_ledger(
    admin: OperatorCtx,
    service: LedgersService,
    org_id: UUID,
    kind: EntryKind | None = None,
    limit: int = LIMIT_DEFAULT,
) -> list[LedgerEntryView]:
    return await service.get_entries(admin, org_id, kind, limit)
