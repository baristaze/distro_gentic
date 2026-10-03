from pydantic import ValidationError

from acme.om.context import OperatorContext, TenantContext
from acme.om.exceptions import NotFound, ValidationFailed
from acme.om.matrix import MatrixManagerInterface, MatrixOperatorManagerInterface
from acme.om.matrix.types.matrix import MatrixKey, MatrixRow
from acme.om.models.types.fill import Fill, ModelRole
from acme.services.api.services.matrix import MatrixServiceInterface
from acme.services.api.types.matrix import (
    ChooseRequest,
    FillBody,
    FillChoiceView,
    FillOptionsView,
    MatrixRowBody,
    MatrixVersionView,
    StageRequest,
)


def fill_of(body: FillBody) -> Fill:
    """The fill a body names; a fill it may not be is `ValidationFailed`."""
    try:
        return Fill.model_validate(body.model_dump())
    except ValidationError as error:
        raise ValidationFailed(f"fill: {error}"[:500]) from None


def row_of(body: MatrixRowBody) -> MatrixRow:
    try:
        return MatrixRow(
            key=MatrixKey.model_validate(body.matches.model_dump()),
            fills=tuple(fill_of(fill) for fill in body.fills),
        )
    except ValidationError as error:
        raise ValidationFailed(f"matrix row: {error}"[:500]) from None


class MatrixServiceImpl(MatrixServiceInterface):
    def __init__(
        self, matrix: MatrixManagerInterface, operators: MatrixOperatorManagerInterface
    ) -> None:
        self._matrix = matrix
        self._operators = operators

    async def get_options(self, ctx: TenantContext) -> list[FillOptionsView]:
        options = await self._matrix.get_options(ctx)
        return [FillOptionsView.model_validate(option) for option in options]

    async def get_choices(self, ctx: TenantContext) -> list[FillChoiceView]:
        choices = await self._matrix.get_choices(ctx)
        return [FillChoiceView.model_validate(choice) for choice in choices]

    async def choose(
        self, ctx: TenantContext, role: ModelRole, body: ChooseRequest
    ) -> FillChoiceView:
        chosen = await self._matrix.choose_fill(ctx, role, fill_of(body.fill))
        return FillChoiceView.model_validate(chosen)

    async def drop_choice(self, ctx: TenantContext, role: ModelRole) -> None:
        if not await self._matrix.drop_choice(ctx, role):
            raise NotFound(f"no choice for the model role {role}")

    async def stage(self, admin: OperatorContext, body: StageRequest) -> MatrixVersionView:
        rows = [row_of(row) for row in body.rows]
        version = await self._operators.stage(admin, body.roles, rows)
        return MatrixVersionView.model_validate(version)

    async def publish(self, admin: OperatorContext, number: int) -> MatrixVersionView:
        return MatrixVersionView.model_validate(await self._operators.publish(admin, number))

    async def get_version(self, admin: OperatorContext, number: int | None) -> MatrixVersionView:
        return MatrixVersionView.model_validate(await self._operators.get_version(admin, number))
