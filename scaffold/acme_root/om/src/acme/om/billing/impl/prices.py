"""The price book over the engine's list table: the one source of prices,
read by version. Every version still published is kept, so a hold read at
one is billed at it after the next is read; a version that is not kept
prices nothing."""

from collections.abc import Sequence
from types import MappingProxyType

from acme.om.billing.prices import PriceBookInterface
from acme.om.budgets.impl.pricing import LIST_PRICES
from acme.om.budgets.pricing import ModelPrice, PriceTable


class PriceBookTableImpl(PriceBookInterface):
    def __init__(self, tables: Sequence[PriceTable] = (LIST_PRICES,)) -> None:
        """`tables` are the published readings, the last in force."""
        if not tables:
            raise ValueError("a price book holds the table in force")
        versions = [table.version for table in tables]
        if len(set(versions)) != len(versions):
            raise ValueError("a price table's version is read once")
        self._version = versions[-1]
        self._rows = MappingProxyType(
            {
                table.version: {(row.provider, row.model): row.price for row in table.rows}
                for table in tables
            }
        )

    @property
    def version(self) -> str:
        return self._version

    def price_of(self, provider: str, model: str) -> ModelPrice | None:
        return self.price_at(self._version, provider, model)

    def price_at(self, version: str, provider: str, model: str) -> ModelPrice | None:
        rows = self._rows.get(version)
        return None if rows is None else rows.get((provider, model))
