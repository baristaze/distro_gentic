"""Wire types of a tenant's billing writes that clear a park: a call
approved past its session's norm, a budget raised once for its window,
and, beside them in `ledgers`, units an operator grants. Each answers the
ledger entry it posted (`LedgerEntryView`)."""

from typing import Self

from pydantic import Field, model_validator

from acme.services.api.types.common import RequestBody

MOST = 10**15
"""The most one write approves, raises, or grants of a unit: a billion of
the reference currency in millionths, far past any real need and far
under what the ledger's counts hold."""


class CostApprovalRequest(RequestBody):
    """A person's yes to the session's next call past its norm, up to a
    reference cost in millionths."""

    up_to_micros: int = Field(gt=0, le=MOST)


class RaiseRequest(RequestBody):
    """A raise of a budget for the window open now: reference cost in
    millionths, native tokens, or both. A unit left out is not raised, and
    a raise raises one at least."""

    cost_micros: int | None = Field(default=None, gt=0, le=MOST)
    tokens: int | None = Field(default=None, gt=0, le=MOST)

    @model_validator(mode="after")
    def _raises_something(self) -> Self:
        if self.cost_micros is None and self.tokens is None:
            raise ValueError("a raise raises reference cost, native tokens, or both")
        return self
