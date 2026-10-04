"""Wire types of a tenant's budgets: a budget a person sets, one budget as
stored, the new amount a person sets on it, and the tenant's usage, each
budget with what its current window spent."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.budgets.types.budget import BudgetScopeKind, WindowKind
from acme.services.api.types.common import RequestBody, View

SettableScope = Literal[BudgetScopeKind.PERSON, BudgetScopeKind.PROJECT, BudgetScopeKind.TENANT]
"""The scopes a person sets a budget over: the ones every model call is
charged to and that outlive a session. A session's and a tree's budgets are
its own bounds, and no call is charged to a team."""


class CreateBudgetRequest(RequestBody):
    """A budget over a scope and a window, in reference cost (millionths),
    native tokens, or both. A person's and a project's scope is keyed by its
    id; a tenant's is the tenant itself, so its key is left out or names the
    tenant. A span window has a length in seconds, and no other window has."""

    scope_kind: SettableScope
    scope_key: UUID | None = None
    window_kind: WindowKind
    window_seconds: int | None = Field(default=None, ge=1)
    cost_micros: int | None = Field(default=None, ge=0)
    tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _a_keyed_scope_names_its_key(self) -> Self:
        if self.scope_kind is not BudgetScopeKind.TENANT and self.scope_key is None:
            raise ValueError("a person's or a project's budget names its id in scope_key")
        return self


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
