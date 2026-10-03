"""The budgets service: read a tenant's budget, set its amount on the
version the caller read, and read the tenant's usage across its budgets."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.budgets import AmountRequest, BudgetView, UsagePageView


class BudgetsServiceInterface(ABC):
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
