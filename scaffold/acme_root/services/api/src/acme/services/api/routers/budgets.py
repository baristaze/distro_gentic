"""A tenant's budgets: read one, and raise or lower its amount on the
version read. A raise wakes the sessions that wait on the budget."""

from uuid import UUID

from fastapi import APIRouter

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.precondition import IfMatch
from acme.services.api.gateway.resolve import BudgetsService
from acme.services.api.types.budgets import AmountRequest, BudgetView

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.get("/{budget_id}", response_model=BudgetView)
async def get_budget(ctx: Ctx, budgets: BudgetsService, budget_id: UUID) -> BudgetView:
    return await budgets.get_budget(ctx, budget_id)


@router.put("/{budget_id}/amount", response_model=BudgetView)
async def change_amount(
    ctx: Ctx, budgets: BudgetsService, budget_id: UUID, body: AmountRequest, version: IfMatch
) -> BudgetView:
    """The budget at its new amount, on the version `If-Match` names."""
    return await budgets.change_amount(ctx, budget_id, body, version)
