"""The sweep's settlement of the holds nobody settled, through the gate that
holds them. It reads the ledger the gate writes, one slice of opening times
at a time, from where its last call stopped: a worker's first call reads a
day back, so a hold the workers were all down for is still found."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field

from acme.om.base import EMPTY_UUID, Platform, utcnow
from acme.om.billing.storage import MoneyLedgerStorageInterface
from acme.om.billing.sweep import HoldSweepInterface, ProviderBillsInterface
from acme.om.budgets.gate import BudgetGateInterface
from acme.om.budgets.storage import LedgerStorageInterface
from acme.om.budgets.types.hold import Bill, BillUnknown, Hold
from acme.om.context import RequestContext
from acme.om.exceptions import InvalidCredential
from acme.om.tenancy import TenancyManagerInterface

log = logging.getLogger(__name__)


class HoldSweepOptions(Platform):
    # A hold open this long has no call left to settle it: a run renews its
    # lease while its call streams, and a run that lost its lease is stopped
    # within half of it. A call still streaming past this finds its hold
    # settled whole, and its own settlement answers that first one.
    settle_after: timedelta = timedelta(hours=1)
    # How far back past `settle_after` a worker's first call reads. Every
    # call after reads on from where the one before stopped.
    lookback: timedelta = timedelta(days=1)
    # One read covers this much of the holds' opening times, so no read walks
    # a day of settled holds to find the open ones; a call reads up to a
    # day of slices, so a worker's first call reads its whole lookback.
    slice: timedelta = timedelta(hours=1)
    slices: int = Field(default=24, gt=0)  # slices one call reads at most
    batch: int = Field(default=100, gt=0)  # holds one read takes at most


class HoldSweepImpl(HoldSweepInterface):
    def __init__(
        self,
        ledger: LedgerStorageInterface | MoneyLedgerStorageInterface,
        gate: BudgetGateInterface,
        tenancy: TenancyManagerInterface,
        bills: ProviderBillsInterface,
        options: HoldSweepOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        """`ledger` is the one `gate` writes its holds to: billing's, behind
        the money gate a root wires, or the engine's, behind its own gate."""
        self._ledger = ledger
        self._gate = gate
        self._tenancy = tenancy
        self._bills = bills
        self._options = options
        self._clock = clock
        # The opening time the next call reads on from; None until this
        # process has read once.
        self._read_to: datetime | None = None

    async def settle_open(self, rctx: RequestContext) -> int:
        options = self._options
        before = self._clock() - options.settle_after
        start = self._read_to or before - options.lookback
        taken = 0
        for _ in range(options.slices):
            if start >= before:
                break
            end = min(start + options.slice, before)
            found = await self._ledger.read_open(start, end, options.batch)
            taken += len(found)
            # A hold that did not settle holds the next call at its time, so
            # it is read again; the ones after it in the batch still settle.
            left = [
                hold.created_at
                for org_id, hold in found
                if not await self._settle(rctx, org_id, hold)
            ]
            if left:
                self._read_to = min(left)
                return taken
            if len(found) >= options.batch:
                # A whole batch: the slice may hold more, read from here on.
                self._read_to = found[-1][1].created_at
                return taken
            start = self._read_to = end
        return taken

    async def _settle(self, rctx: RequestContext, org_id: UUID, hold: Hold) -> bool:
        """Settles one hold through its gate; False when it is left for the
        next call. A hold of a deleted tenant is left for good, as the rest of
        its ledger is."""
        try:
            ctx = await self._tenancy.service_context(rctx, org_id, EMPTY_UUID)
        except InvalidCredential:
            return True
        bill = await self._bill(org_id, hold)
        try:
            settled = await self._gate.settle(ctx, hold.id, bill)
        except Exception:
            log.exception("hold %s of org %s waits for the next pass", hold.id, org_id)
            return False
        log.info(
            "hold %s of org %s, opened at %s, settled by the sweep: %s, %d micros",
            hold.id,
            org_id,
            hold.created_at.isoformat(),
            settled.bill.kind,
            settled.spent.cost_micros,
        )
        return True

    async def _bill(self, org_id: UUID, hold: Hold) -> Bill:
        """What the provider says it billed, else the whole hold: a provider
        that cannot say, or cannot be asked, never lets a hold count less."""
        try:
            retrieved = await self._bills.retrieve(org_id, hold)
        except Exception:
            log.exception("the bill of hold %s could not be retrieved; it counts whole", hold.id)
            return BillUnknown()
        return retrieved if retrieved is not None else BillUnknown()
