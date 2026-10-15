from uuid import UUID

from acme.om.agent_billing import AgentBillingManagerInterface
from acme.om.base import utcnow
from acme.om.context import TenantContext
from acme.om.exceptions import ValidationFailed
from acme.om.spend_budgets import SpendBudgetsManagerInterface
from acme.om.spend_budgets.types.amount import Amount
from acme.om.spend_budgets.types.spend_budget import SpendBudget, SpendBudgetScopeKind
from acme.services.api.services.budgets import BudgetsServiceInterface
from acme.services.api.services.impl.built import built
from acme.services.api.services.impl.tenancy import decode_cursor, encode_cursor
from acme.services.api.types.common import clamp_limit
from acme.services.api.types.spend_budgets import (
    AmountRequest,
    BudgetUsageView,
    BudgetView,
    CreateBudgetRequest,
    SettableScope,
    UsagePageView,
)

USAGE = "usage"


class BudgetsServiceImpl(BudgetsServiceInterface):
    def __init__(
        self, budgets: SpendBudgetsManagerInterface, agent_billing: AgentBillingManagerInterface
    ) -> None:
        """`agent_billing` reads each budget's spend from the one ledger the money
        gate holds and settles in, in the tenant's own windows."""
        self._budgets = budgets
        self._agent_billing = agent_billing

    async def create_spend_budget(
        self, ctx: TenantContext, body: CreateBudgetRequest, spend_budget_id: UUID
    ) -> BudgetView:
        key = body.scope_key
        if body.scope_kind is SettableScope.TENANT:
            # The gate charges a tenant's scope under the tenant's own id, so
            # any other key is a budget nothing would ever be held to.
            if key not in (None, ctx.org_id):
                raise ValidationFailed("scope_key: a tenant's budget is the tenant's own")
            key = ctx.org_id
        now = utcnow()
        budget = built(
            SpendBudget,
            {
                "id": spend_budget_id,
                "created_at": now,
                "updated_at": now,
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
                "scope_kind": SpendBudgetScopeKind(body.scope_kind),
                "scope_key": str(key),
                "window_kind": body.window_kind,
                "window_seconds": body.window_seconds,
                "cost_micros": body.cost_micros,
                "tokens": body.tokens,
            },
        )
        return BudgetView.model_validate(await self._budgets.create_spend_budget(ctx, budget))

    async def list_budgets(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> list[BudgetView]:
        page = await self._budgets.get_spend_budgets(ctx, after, clamp_limit(limit))
        return [BudgetView.model_validate(budget) for budget in page.items]

    async def get_spend_budget(self, ctx: TenantContext, spend_budget_id: UUID) -> BudgetView:
        return BudgetView.model_validate(await self._budgets.get_spend_budget(ctx, spend_budget_id))

    async def change_amount(
        self, ctx: TenantContext, spend_budget_id: UUID, body: AmountRequest, version: int | None
    ) -> BudgetView:
        if version is None:
            raise ValidationFailed("a change of amount names the version it read, in If-Match")
        amount = Amount(cost_micros=body.cost_micros, tokens=body.tokens)
        changed = await self._budgets.change_amount(ctx, spend_budget_id, amount, version)
        return BudgetView.model_validate(changed)

    async def get_usage(self, ctx: TenantContext, cursor: str | None, limit: int) -> UsagePageView:
        after = decode_cursor(USAGE, cursor) if cursor else None
        page = await self._budgets.get_spend_budgets(ctx, after, clamp_limit(limit))
        items: list[BudgetUsageView] = []
        for budget in page.items:
            tally = await self._agent_billing.get_spend(ctx, budget.id)
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
