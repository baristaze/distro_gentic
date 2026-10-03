from uuid import UUID

from acme.om.budgets import BudgetsManagerInterface
from acme.om.budgets.types.amount import Amount
from acme.om.context import TenantContext
from acme.om.exceptions import ValidationFailed
from acme.services.api.services.budgets import BudgetsServiceInterface
from acme.services.api.services.impl.tenancy import decode_cursor, encode_cursor
from acme.services.api.types.budgets import (
    AmountRequest,
    BudgetUsageView,
    BudgetView,
    UsagePageView,
)
from acme.services.api.types.common import clamp_limit

USAGE = "usage"


class BudgetsServiceImpl(BudgetsServiceInterface):
    def __init__(self, budgets: BudgetsManagerInterface) -> None:
        self._budgets = budgets

    async def get_budget(self, ctx: TenantContext, budget_id: UUID) -> BudgetView:
        return BudgetView.model_validate(await self._budgets.get_budget(ctx, budget_id))

    async def change_amount(
        self, ctx: TenantContext, budget_id: UUID, body: AmountRequest, version: int | None
    ) -> BudgetView:
        if version is None:
            raise ValidationFailed("a change of amount names the version it read, in If-Match")
        amount = Amount(cost_micros=body.cost_micros, tokens=body.tokens)
        changed = await self._budgets.change_amount(ctx, budget_id, amount, version)
        return BudgetView.model_validate(changed)

    async def get_usage(self, ctx: TenantContext, cursor: str | None, limit: int) -> UsagePageView:
        after = decode_cursor(USAGE, cursor) if cursor else None
        page = await self._budgets.get_budgets(ctx, after, clamp_limit(limit))
        items: list[BudgetUsageView] = []
        for budget in page.items:
            tally = await self._budgets.get_spend(ctx, budget.id)
            items.append(
                BudgetUsageView(
                    budget=BudgetView.model_validate(budget),
                    window_start=tally.window_start,
                    held_cost_micros=tally.held_cost_micros,
                    held_tokens=tally.held_tokens,
                    spent_cost_micros=tally.spent_cost_micros,
                    spent_tokens=tally.spent_tokens,
                )
            )
        last = page.items[-1].id if page.items and page.has_more else None
        return UsagePageView(
            items=items, next_cursor=None if last is None else encode_cursor(USAGE, last)
        )
