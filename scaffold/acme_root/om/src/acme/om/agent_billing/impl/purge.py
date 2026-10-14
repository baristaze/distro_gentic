from acme.om.billing.purge import BillingPurgeInterface
from acme.om.billing.storage import AccountStorageInterface
from acme.om.context import Permission, TenantContext
from acme.om.tenancy import TenancyManagerInterface


class BillingPurgeImpl(BillingPurgeInterface):
    def __init__(
        self,
        accounts: AccountStorageInterface,
        tenancy: TenancyManagerInterface,
    ) -> None:
        self._accounts = accounts
        self._tenancy = tenancy

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._accounts.purge_tenant(ctx.org_id)
