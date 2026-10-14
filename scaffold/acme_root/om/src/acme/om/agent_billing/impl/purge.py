from acme.om.agent_billing.purge import AgentBillingPurgeInterface
from acme.om.agent_billing.storage import SpendAccountStorageInterface
from acme.om.context import Permission, TenantContext
from acme.om.tenancy import TenancyManagerInterface


class AgentBillingPurgeImpl(AgentBillingPurgeInterface):
    def __init__(
        self,
        spend_accounts: SpendAccountStorageInterface,
        tenancy: TenancyManagerInterface,
    ) -> None:
        self._spend_accounts = spend_accounts
        self._tenancy = tenancy

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._spend_accounts.purge_tenant(ctx.org_id)
