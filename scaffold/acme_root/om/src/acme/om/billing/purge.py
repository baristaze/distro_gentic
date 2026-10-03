"""Billing's part of a deleted tenant's purge: its account goes with its
other rows, and its ledger, which no serving login deletes, is counted, so
the sweep never marks the tenant purged while any of it remains."""

from abc import ABC, abstractmethod

from acme.om.context import TenantContext


class BillingPurgeInterface(ABC):
    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: deletes its
        account, and answers how many rows went. Any other tenant returns 0
        and reads nothing."""
        ...

    @abstractmethod
    async def purge_ledger(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention. No serving login
        may delete an entry, so it deletes nothing: it answers how many
        entries and counts the tenant still keeps, fewer than a whole batch,
        so the sweep never marks the tenant purged while its ledger remains
        and does not call again in the same pass. Any other tenant returns 0
        and reads nothing."""
        ...
