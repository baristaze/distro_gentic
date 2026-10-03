"""Wire types of a tenant's budgets: one budget as stored, the new amount a
person sets on it, and the tenant's usage, each budget with what its
current window spent."""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.budgets.types.budget import BudgetScopeKind, WindowKind
from acme.services.api.types.common import RequestBody, View


class BudgetView(View):
    """A budget: its scope, its window, its amount, and the version a change
    of the amount names in `If-Match`."""

    id: UUID
    scope_kind: BudgetScopeKind
    scope_key: str
    window_kind: WindowKind
    window_seconds: int | None
    cost_micros: int | None
    tokens: int | None
    version: int


class AmountRequest(RequestBody):
    """A budget's new amount: reference cost in millionths, native tokens, or
    both. A unit left out is not bounded, and an amount bounds one at least."""

    cost_micros: int | None = Field(default=None, ge=0)
    tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _bounds_something(self) -> Self:
        if self.cost_micros is None and self.tokens is None:
            raise ValueError("an amount bounds reference cost, native tokens, or both")
        return self


class BudgetUsageView(View):
    """A budget and its current window: what open holds reserve and what
    settled calls spent, in reference cost (millionths) and native tokens,
    against the budget's amount."""

    budget: BudgetView
    window_start: datetime
    held_cost_micros: int
    held_tokens: int
    spent_cost_micros: int
    spent_tokens: int


class UsagePageView(View):
    """One page of the tenant's budgets with their usage, by budget id.
    `next_cursor` fetches the next page and is null on the last one."""

    items: list[BudgetUsageView]
    next_cursor: str | None
