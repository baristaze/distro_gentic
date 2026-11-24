import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError

from acme.om.base import EMPTY_UUID, new_id, utcnow
from acme.om.change_events.storage import ChangeEventStorageInterface
from acme.om.change_events.types.change_event import ChangeEvent
from acme.om.cloud_pool.impl.manager import CloudPoolOptions, standing_limits
from acme.om.cloud_pool.operator import CloudPoolOperatorManagerInterface
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.types.limits import PoolLimits, TenantPoolLimit
from acme.om.context import OperatorContext, OperatorPermission
from acme.om.exceptions import NotFound, ValidationFailed
from acme.om.tenancy.storage import TenancyStorageInterface

log = logging.getLogger(__name__)

LIMITS_SET_KIND = "cloud_pool.limits.set"
"""The audit event an operator's write of the pool's limits leaves in the
platform's stream."""

TENANT_LIMIT_SET_KIND = "cloud_pool.tenant_limit.set"
"""The audit event an operator's write of a tenant's own maximum leaves in
the tenant's stream."""

TENANT_LIMIT_CLEARED_KIND = "cloud_pool.tenant_limit.cleared"
"""The audit event an operator's clearing of a tenant's own maximum leaves
in the tenant's stream."""


class CloudPoolOperatorManagerImpl(CloudPoolOperatorManagerInterface):
    """Writes the pool's limits and a tenant's own maximum through the
    pool's storage, and reads the org through its storage, as the other
    operator planes do: no `TenantContext` exists on this plane. A write
    lands first and its event after: a crash between the two loses the
    entry, never the write."""

    def __init__(
        self,
        storage: CloudPoolStorageInterface,
        tenancy: TenancyStorageInterface,
        events: ChangeEventStorageInterface,
        options: CloudPoolOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._change_events = events
        self._options = options
        self._clock = clock

    async def get_limits(self, admin: OperatorContext) -> PoolLimits:
        admin.require(OperatorPermission.READ)
        return standing_limits(await self._storage.read_limits(), self._options, self._clock())

    async def set_limits(
        self,
        admin: OperatorContext,
        *,
        warm: int,
        most: int,
        tenant_most: int,
        hibernated: int = 0,
    ) -> PoolLimits:
        admin.require(OperatorPermission.WRITE)
        stored = await self._storage.read_limits()
        now = self._clock()
        # Each write is a row of its own: an operator has no user in a
        # tenant, so the identity is the actor.
        try:
            limits = PoolLimits(
                id=new_id(),
                created_at=now,
                updated_at=now,
                created_by=admin.identity_id,
                updated_by=admin.identity_id,
                warm=warm,
                hibernated=hibernated,
                most=most,
                tenant_most=tenant_most,
                version=1 if stored is None else stored.version + 1,
            )
        except ValidationError as error:
            raise ValidationFailed(f"the cloud pool's limits: {error}"[:500]) from None
        written = await self._storage.write_limits(
            limits, None if stored is None else stored.version
        )
        log.info(
            "operator %s set the cloud pool's limits: %d warm, %d hibernated, %d at most, "
            "%d a tenant",
            admin.identity_id,
            warm,
            hibernated,
            most,
            tenant_most,
        )
        await self._audit(
            admin,
            EMPTY_UUID,
            LIMITS_SET_KIND,
            written.id,
            {
                "warm": written.warm,
                "hibernated": written.hibernated,
                "most": written.most,
                "tenant_most": written.tenant_most,
                "version": written.version,
            },
        )
        return written

    async def set_tenant_limit(
        self, admin: OperatorContext, org_id: UUID, *, most: int
    ) -> TenantPoolLimit:
        admin.require(OperatorPermission.WRITE)
        org = await self._tenancy.read_org(org_id)
        if org is None or org.deleted_at is not None:
            raise NotFound(f"org {org_id} not found")
        stored = await self._storage.read_tenant_limit(org_id)
        now = self._clock()
        try:
            if stored is None:
                limit = TenantPoolLimit(
                    id=new_id(),
                    created_at=now,
                    updated_at=now,
                    created_by=admin.identity_id,
                    updated_by=admin.identity_id,
                    most=most,
                )
            else:
                limit = TenantPoolLimit.model_validate(
                    {
                        **stored.model_dump(),
                        "most": most,
                        "version": stored.version + 1,
                        "updated_at": now,
                        "updated_by": admin.identity_id,
                    }
                )
        except ValidationError as error:
            raise ValidationFailed(f"org {org_id}'s VM maximum: {error}"[:500]) from None
        written = await self._storage.write_tenant_limit(
            org_id, limit, None if stored is None else stored.version
        )
        log.info(
            "operator %s set org %s's maximum of cloud VMs: %d", admin.identity_id, org_id, most
        )
        await self._audit(
            admin,
            org_id,
            TENANT_LIMIT_SET_KIND,
            written.id,
            {"most": written.most, "version": written.version},
        )
        return written

    async def clear_tenant_limit(self, admin: OperatorContext, org_id: UUID) -> TenantPoolLimit:
        admin.require(OperatorPermission.WRITE)
        removed = await self._storage.delete_tenant_limit(org_id)
        if removed is None:
            raise NotFound(f"org {org_id} has no maximum of cloud VMs of its own")
        log.info("operator %s cleared org %s's maximum of cloud VMs", admin.identity_id, org_id)
        await self._audit(
            admin, org_id, TENANT_LIMIT_CLEARED_KIND, removed.id, {"version": removed.version}
        )
        return removed

    async def _audit(
        self,
        admin: OperatorContext,
        org_id: UUID,
        kind: str,
        target_id: UUID,
        payload: dict[str, int],
    ) -> None:
        """The event that names the write and who made it, with the values
        it set: in the tenant's stream for a tenant's own maximum, and in the
        platform's, the system scope's, for the pool's own limits, so no
        tenant reads the pool's size."""
        await self._change_events.append_change_events(
            org_id,
            [
                ChangeEvent(
                    id=new_id(),
                    org_id=org_id,
                    kind=kind,
                    target_id=target_id,
                    payload=payload,
                    produced_at=self._clock(),
                    actor_id=admin.identity_id,
                    request_id=admin.request_id,
                    app=admin.app.type.value,
                )
            ],
        )
