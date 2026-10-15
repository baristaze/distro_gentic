"""The ledger contract's case for the method the platform adds to it: the
sweep's read, across tenants, of the holds no settlement closed."""

from datetime import datetime, timedelta

import pytest

from acme.om.base import new_id, utcnow
from acme.om.spend_budgets.rules import spend_settlement_of
from acme.om.spend_budgets.storage import LedgerStorageInterface
from acme.om.spend_budgets.types.spend_hold import BillUnknown, SpendHold

from contracts.ledger_storage import a_hold, a_line


class PlatformLedgerStorageContract:
    @pytest.fixture
    def storage(self) -> LedgerStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_read_open_answers_the_slices_unsettled_holds_oldest_first(
        self, storage: LedgerStorageInterface
    ) -> None:
        """The sweep's read across tenants: every hold opened in the slice
        that no settlement closed, each with its tenant, oldest first, a batch
        at most; never one settled, nor one opened outside the slice."""
        first, second, now = new_id(), new_id(), utcnow()
        line = a_line(cost_micros=100_000)

        def opened(at: datetime) -> SpendHold:
            return a_hold(line).model_copy(update={"created_at": at})

        old, older, settled = (opened(now - timedelta(hours=h)) for h in (2, 3, 4))
        recent, ancient = opened(now - timedelta(minutes=5)), opened(now - timedelta(days=2))
        for org, hold in (
            (first, old),
            (second, older),
            (first, settled),
            (first, recent),
            (second, ancient),
        ):
            assert await storage.open_spend_hold(org, hold) is None
        await storage.close_spend_hold(
            first, spend_settlement_of(settled, BillUnknown(), new_id(), now)
        )
        floor, cut = now - timedelta(days=1), now - timedelta(hours=1)
        found = await storage.read_open(floor, cut, 10)
        assert [(org, hold.id, due) for org, hold, due in found] == [
            (second, older.id, older.created_at),
            (first, old.id, old.created_at),
        ]
        assert found[0][1] == older
        assert [hold.id for _, hold, _ in await storage.read_open(floor, cut, 1)] == [older.id]
