"""A tenant's budgets: set one over a scope and a window, list and read
them, and raise or lower one's amount on the version read. A raise wakes
the sessions that wait on the budget. Setting a budget or its amount takes
the permission that governs members; reading one is any member's.

The tenant's usage: each of its budgets with what its current window
holds and spent, a page at a time. A budget's amount is changed on its own
route."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.platform_resolve import BudgetsService
from acme.services.api.gateway.precondition import IfMatch
from acme.services.api.types.common import LIMIT_DEFAULT
from acme.services.api.types.spend_budgets import (
    AmountRequest,
    BudgetView,
    CreateBudgetRequest,
    UsagePageView,
)

router = APIRouter(prefix="/spend-budgets", tags=["spend_budgets"])


usage = APIRouter(prefix="/usage", tags=["spend_budgets"])


@router.post("", response_model=BudgetView, status_code=201)
async def create_spend_budget(
    ctx: Ctx, budgets: BudgetsService, body: CreateBudgetRequest, idem: Idem
) -> Response:
    """A budget every model call charged to its scope is held to, from the
    next call on."""
    return await idem.run(
        201, lambda attempt: budgets.create_spend_budget(ctx, body, attempt.target_id)
    )


@router.get("", response_model=list[BudgetView])
async def list_budgets(
    ctx: Ctx, budgets: BudgetsService, after: UUID | None = None, limit: int = LIMIT_DEFAULT
) -> list[BudgetView]:
    """The tenant's budgets by id, after the id `after` names."""
    return await budgets.list_budgets(ctx, after, limit)


@router.get("/{spend_budget_id}", response_model=BudgetView)
async def get_spend_budget(ctx: Ctx, budgets: BudgetsService, spend_budget_id: UUID) -> BudgetView:
    return await budgets.get_spend_budget(ctx, spend_budget_id)


@router.put("/{spend_budget_id}/amount", response_model=BudgetView)
async def change_amount(
    ctx: Ctx, budgets: BudgetsService, spend_budget_id: UUID, body: AmountRequest, version: IfMatch
) -> BudgetView:
    """The budget at its new amount, on the version `If-Match` names."""
    return await budgets.change_amount(ctx, spend_budget_id, body, version)


@usage.get("", response_model=UsagePageView)
async def get_usage(
    ctx: Ctx,
    budgets: BudgetsService,
    cursor: str | None = None,
    limit: int = LIMIT_DEFAULT,
) -> UsagePageView:
    return await budgets.get_usage(ctx, cursor, limit)
