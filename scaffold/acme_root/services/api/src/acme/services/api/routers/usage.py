"""The tenant's usage: each of its budgets with what its current window
holds and spent, a page at a time. A budget's amount is changed on its own
route."""

from fastapi import APIRouter

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.resolve import BudgetsService
from acme.services.api.types.budgets import UsagePageView
from acme.services.api.types.common import LIMIT_DEFAULT

router = APIRouter(prefix="/usage", tags=["budgets"])


@router.get("", response_model=UsagePageView)
async def get_usage(
    ctx: Ctx,
    budgets: BudgetsService,
    cursor: str | None = None,
    limit: int = LIMIT_DEFAULT,
) -> UsagePageView:
    return await budgets.get_usage(ctx, cursor, limit)
