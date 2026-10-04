"""The budgets service: set a tenant's budget, list and read its budgets,
set one's amount on the version the caller read, and read the tenant's
usage across its budgets."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.budgets import (
    AmountRequest,
    BudgetView,
    CreateBudgetRequest,
    UsagePageView,
)


class BudgetsServiceInterface(ABC):
    @abstractmethod
    async def create_budget(
        self, ctx: TenantContext, body: CreateBudgetRequest, budget_id: UUID
    ) -> BudgetView:
        """The budget under the id the edge gives it; a retry under that id
        answers the budget as stored. A tenant key that names another tenant,
        or a window or an amount its rules refuse, is `ValidationFailed`."""
        ...

    @abstractmethod
    async def list_budgets(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> list[BudgetView]: ...

    @abstractmethod
    async def get_budget(self, ctx: TenantContext, budget_id: UUID) -> BudgetView: ...

    @abstractmethod
    async def change_amount(
        self, ctx: TenantContext, budget_id: UUID, body: AmountRequest, version: int | None
    ) -> BudgetView:
        """The new amount, on the version the caller read: none named is
        `ValidationFailed`, and one that moved is `PreconditionFailed`."""
        ...

    @abstractmethod
    async def get_usage(self, ctx: TenantContext, cursor: str | None, limit: int) -> UsagePageView:
        """One page of the tenant's budgets, each with what its current
        window holds and spent."""
        ...
