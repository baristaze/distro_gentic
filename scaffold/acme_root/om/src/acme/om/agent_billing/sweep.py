"""The sweep's duty for a hold nobody settled: the gate held a call's worst
case, and the run that made the call died before it settled the hold. The
call may have been billed, so the hold settles at the usage retrieved from
the provider, else at its full amount, and is released only when the
provider provably did not bill. Until it settles, it reserves its lines and
its spend counts nowhere."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.budgets.types.hold import Bill, Hold
from acme.om.context import RequestContext


class ProviderBillsInterface(ABC):
    @abstractmethod
    async def retrieve(self, org_id: UUID, hold: Hold) -> Bill | None:
        """What the provider says it billed for the call `hold` covers: the
        usage, priced at list price, or that it billed nothing, with the
        proof. None when it cannot say."""
        ...

    @abstractmethod
    def describe(self) -> str: ...


class ProviderBillsUnknownImpl(ProviderBillsInterface):
    """The provider's bills where none can be asked for one call after the
    fact: every hold the sweep finds counts whole, which never counts less
    than the provider billed."""

    async def retrieve(self, org_id: UUID, hold: Hold) -> Bill | None:
        return None

    def describe(self) -> str:
        return "provider_bills=unknown"


class HoldSweepInterface(ABC):
    @abstractmethod
    async def settle_open(self, rctx: RequestContext) -> int:
        """Platform-internal: the sweep, across tenants, once a pass, under a
        service context minted for each tenant from `rctx`. Each hold open
        longer than any call it covers can last, and that no settlement has
        closed, settles once through the gate: at the bill the provider
        gives, else whole. A hold of a deleted tenant is left as its ledger
        is. Returns how many holds it took up, so a whole batch says there
        may be more."""
        ...
