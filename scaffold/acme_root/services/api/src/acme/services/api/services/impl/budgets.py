from uuid import UUID

from acme.om.budgets import BudgetsManagerInterface
from acme.om.budgets.types.amount import Amount
from acme.om.context import TenantContext
from acme.om.exceptions import ValidationFailed
from acme.services.api.services.budgets import BudgetsServiceInterface
from acme.services.api.types.budgets import AmountRequest, BudgetView


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
