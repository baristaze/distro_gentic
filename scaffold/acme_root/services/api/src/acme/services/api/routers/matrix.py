"""A tenant's part of the model matrix: what it may choose from, its
choices, and a choice made or dropped. A tenant names a model only when it
pays its providers on its own keys, and then only among the fills the
published matrix qualified for the role, from a provider it holds a live
key for; the manager refuses any other. A choice is written whole for its
role, so the write is a PUT and a retry lands the same choice: it takes no
Idempotency-Key."""

from fastapi import APIRouter

from acme.om.models.types.fill import ModelRole
from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.resolve import MatrixService
from acme.services.api.types.matrix import ChooseRequest, FillChoiceView, FillOptionsView

router = APIRouter(prefix="/matrix", tags=["matrix"])


@router.get("/options", response_model=list[FillOptionsView])
async def get_options(ctx: Ctx, service: MatrixService) -> list[FillOptionsView]:
    """For each model role of the published matrix, the fills the tenant
    may choose: none unless it pays its providers on its own keys."""
    return await service.get_options(ctx)


@router.get("/choices", response_model=list[FillChoiceView])
async def get_choices(ctx: Ctx, service: MatrixService) -> list[FillChoiceView]:
    return await service.get_choices(ctx)


@router.put("/choices/{role}", response_model=FillChoiceView)
async def choose(
    ctx: Ctx, service: MatrixService, role: ModelRole, body: ChooseRequest
) -> FillChoiceView:
    """The tenant's fill for `role` from its next session on, one of the
    role's options; it replaces the last. Requires managing the org."""
    return await service.choose(ctx, role, body)


@router.delete("/choices/{role}", status_code=204)
async def drop_choice(ctx: Ctx, service: MatrixService, role: ModelRole) -> None:
    """The matrix answers `role` again. Requires managing the org."""
    await service.drop_choice(ctx, role)
