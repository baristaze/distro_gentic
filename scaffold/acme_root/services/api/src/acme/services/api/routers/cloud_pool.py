"""The cloud pool. On the operator plane, under /v1/admin/*, an operator who
may write sets the pool's limits, a new version each time: the VMs kept
warm, the most VMs it holds at once, and the most one tenant holds; and a
tenant's own maximum, or clears it. Each claim reads them as they stand,
so a write holds with no deploy. A limit is written whole, so the write is
a PUT and a retry lands the same values, with no Idempotency-Key. Each
write leaves an entry that names the operator: the pool's own in the
platform's stream, which no tenant reads, and a tenant's own in the
tenant's."""

from uuid import UUID

from fastapi import APIRouter

from acme.services.api.gateway.admin import OperatorCtx
from acme.services.api.gateway.platform_resolve import AgentFleetService
from acme.services.api.types.cloud_pool import (
    PoolLimitsView,
    SetPoolLimitsRequest,
    SetTenantPoolLimitRequest,
    TenantPoolLimitView,
)

operator = APIRouter(prefix="/admin", tags=["cloud_pool"])


@operator.get("/cloud-pool/limits", response_model=PoolLimitsView)
async def get_pool_limits(admin: OperatorCtx, service: AgentFleetService) -> PoolLimitsView:
    """The pool's limits as the next claim reads them. Requires the read
    permission."""
    return await service.get_pool_limits(admin)


@operator.put("/cloud-pool/limits", response_model=PoolLimitsView)
async def set_pool_limits(
    admin: OperatorCtx, service: AgentFleetService, body: SetPoolLimitsRequest
) -> PoolLimitsView:
    """Writes the pool's limits, a new version, with an entry in the
    platform's stream that names the operator and the values. The next
    claim and the next refill hold to them; a VM already held stays.
    Requires the write permission."""
    return await service.set_pool_limits(admin, body)


@operator.put("/orgs/{org_id}/cloud-pool/limit", response_model=TenantPoolLimitView)
async def set_tenant_pool_limit(
    admin: OperatorCtx, service: AgentFleetService, org_id: UUID, body: SetTenantPoolLimitRequest
) -> TenantPoolLimitView:
    """Writes the org's own maximum of the pool's VMs, in place of the
    pool's, with an entry in the org's stream that names the operator.
    Requires the write permission."""
    return await service.set_tenant_pool_limit(admin, org_id, body)


@operator.delete("/orgs/{org_id}/cloud-pool/limit", response_model=TenantPoolLimitView)
async def clear_tenant_pool_limit(
    admin: OperatorCtx, service: AgentFleetService, org_id: UUID
) -> TenantPoolLimitView:
    """Clears the org's own maximum, so the pool's holds again, with an
    entry in the org's stream that names the operator, and answers the one
    cleared. Requires the write permission."""
    return await service.clear_tenant_pool_limit(admin, org_id)
