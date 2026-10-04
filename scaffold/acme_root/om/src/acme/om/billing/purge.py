"""Billing's part of a deleted tenant's purge: its account goes with its
other rows. Its ledger, which no serving login deletes, stays, and never
keeps the tenant from being marked purged (ADR 1017)."""

from abc import ABC, abstractmethod

from acme.om.context import TenantContext


class BillingPurgeInterface(ABC):
    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: deletes its
        account, and answers how many rows went. Any other tenant returns 0
        and reads nothing."""
        ...
