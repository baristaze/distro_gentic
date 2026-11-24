"""The operators' plane of the cloud pool: its limits, which no tenant
writes. The pool's own are the warm VMs it keeps started ahead of
demand, running and hibernated, the most VMs it holds at once, and the most one tenant holds; a
tenant may have a maximum of its own in place of the last. Every claim
and every refill reads them as they stand, so a write takes effect with
no deploy. Each write leaves an audit event that names the operator and
the values: the pool's own in the platform's stream, which no tenant
reads, and a tenant's own in that tenant's."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.cloud_pool.types.limits import PoolLimits, TenantPoolLimit
from acme.om.context import OperatorContext


class CloudPoolOperatorManagerInterface(ABC):
    @abstractmethod
    async def get_limits(self, admin: OperatorContext) -> PoolLimits:
        """The pool's limits as the next claim reads them: the operators'
        last write, else the pool's options, at version 0. Requires the
        read permission."""
        ...

    @abstractmethod
    async def set_limits(
        self,
        admin: OperatorContext,
        *,
        warm: int,
        most: int,
        tenant_most: int,
        hibernated: int = 0,
    ) -> PoolLimits:
        """Writes the pool's limits, a new version, and leaves an audit
        event in the platform's stream that names the operator and the
        values. The next claim and the next refill hold to them; a VM
        already held stays. `hibernated` warm VMs sleep beside the `warm`
        that run, where the VMs hibernate. Requires the write permission.
        ValidationFailed when a value is out of its bounds, or the warm
        VMs, running and hibernated, do not stand below the most;
        PreconditionFailed when another write landed meanwhile."""
        ...

    @abstractmethod
    async def set_tenant_limit(
        self, admin: OperatorContext, org_id: UUID, *, most: int
    ) -> TenantPoolLimit:
        """Writes the tenant's own maximum, its first or a new version, in
        place of the pool's `tenant_most`, and leaves an audit event in the
        tenant's stream that names the operator and the value. Requires the
        write permission. NotFound when the org is not there or is deleted;
        ValidationFailed when the value is out of its bounds."""
        ...

    @abstractmethod
    async def clear_tenant_limit(self, admin: OperatorContext, org_id: UUID) -> TenantPoolLimit:
        """Clears the tenant's own maximum, so the pool's `tenant_most`
        holds again, and leaves an audit event in the tenant's stream that
        names the operator. Requires the write permission. NotFound when
        the tenant has none."""
        ...
