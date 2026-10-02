"""The one price source, by version. The engine's list table is the source;
this is the face billing reads it through: the version in force, and the
price of a model at any version still published, so a call held at one
version is billed at it after the next is read. There is no second table
and no default row."""

from abc import abstractmethod

from acme.om.budgets.pricing import ModelPrice, PricingInterface


class PriceBookInterface(PricingInterface):
    """The engine's pricing at the version in force (`price_of`), and every
    version beside it."""

    @property
    @abstractmethod
    def version(self) -> str:
        """The version of the table in force."""
        ...

    @abstractmethod
    def price_at(self, version: str, provider: str, model: str) -> ModelPrice | None:
        """The model's price in the table of `version`, or None when that
        version has no row for it or is not published: never a default
        row's, and never another version's."""
        ...
