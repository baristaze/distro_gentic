from acme.om.base import Platform
from acme.om.billing.purge import BillingPurgeInterface
from acme.om.billing.storage import AccountStorageInterface, MoneyLedgerStorageInterface
from acme.om.context import Permission, TenantContext
from acme.om.tenancy import TenancyManagerInterface


class BillingPurgeOptions(Platform):
    purge_batch: int = 1000  # the sweep's batch, which a report of what is left stays under


class BillingPurgeImpl(BillingPurgeInterface):
    def __init__(
        self,
        accounts: AccountStorageInterface,
        ledger: MoneyLedgerStorageInterface,
        tenancy: TenancyManagerInterface,
        options: BillingPurgeOptions,
    ) -> None:
        self._accounts = accounts
        self._ledger = ledger
        self._tenancy = tenancy
        self._options = options

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._accounts.purge_tenant(ctx.org_id)

    async def purge_ledger(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._ledger.count_tenant(ctx.org_id, max(1, self._options.purge_batch - 1))
