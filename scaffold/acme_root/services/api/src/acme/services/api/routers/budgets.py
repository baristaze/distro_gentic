"""A tenant's budgets: set one over a scope and a window, list and read
them, and raise or lower one's amount on the version read. A raise wakes
the sessions that wait on the budget. Setting a budget or its amount takes
the permission that governs members; reading one is any member's."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.precondition import IfMatch
from acme.services.api.gateway.resolve import BudgetsService
from acme.services.api.types.budgets import AmountRequest, BudgetView, CreateBudgetRequest
from acme.services.api.types.common import LIMIT_DEFAULT

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.post("", response_model=BudgetView, status_code=201)
async def create_budget(
    ctx: Ctx, budgets: BudgetsService, body: CreateBudgetRequest, idem: Idem
) -> Response:
    """A budget every model call charged to its scope is held to, from the
    next call on."""
    return await idem.run(201, lambda attempt: budgets.create_budget(ctx, body, attempt.target_id))


@router.get("", response_model=list[BudgetView])
async def list_budgets(
    ctx: Ctx, budgets: BudgetsService, after: UUID | None = None, limit: int = LIMIT_DEFAULT
) -> list[BudgetView]:
    """The tenant's budgets by id, after the id `after` names."""
    return await budgets.list_budgets(ctx, after, limit)


@router.get("/{budget_id}", response_model=BudgetView)
async def get_budget(ctx: Ctx, budgets: BudgetsService, budget_id: UUID) -> BudgetView:
    return await budgets.get_budget(ctx, budget_id)


@router.put("/{budget_id}/amount", response_model=BudgetView)
async def change_amount(
    ctx: Ctx, budgets: BudgetsService, budget_id: UUID, body: AmountRequest, version: IfMatch
) -> BudgetView:
    """The budget at its new amount, on the version `If-Match` names."""
    return await budgets.change_amount(ctx, budget_id, body, version)
