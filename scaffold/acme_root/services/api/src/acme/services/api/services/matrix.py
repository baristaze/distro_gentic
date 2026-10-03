"""The matrix service: what a tenant on its own keys may choose and its
choices, and the operator's stage, publish, and read of a version."""

from abc import ABC, abstractmethod

from acme.om.context import OperatorContext, TenantContext
from acme.om.models.types.fill import ModelRole
from acme.services.api.types.matrix import (
    ChooseRequest,
    FillChoiceView,
    FillOptionsView,
    MatrixVersionView,
    StageRequest,
)


class MatrixServiceInterface(ABC):
    @abstractmethod
    async def get_options(self, ctx: TenantContext) -> list[FillOptionsView]:
        """For each model role of the published matrix, the fills the tenant
        may choose: none unless it pays its providers on its own keys."""
        ...

    @abstractmethod
    async def get_choices(self, ctx: TenantContext) -> list[FillChoiceView]: ...

    @abstractmethod
    async def choose(
        self, ctx: TenantContext, role: ModelRole, body: ChooseRequest
    ) -> FillChoiceView:
        """The tenant's choice for `role`, which replaces the last; a fill
        the tenant may not choose is `ValidationFailed`."""
        ...

    @abstractmethod
    async def drop_choice(self, ctx: TenantContext, role: ModelRole) -> None:
        """The choice for `role` goes; `NotFound` when there was none."""
        ...

    @abstractmethod
    async def stage(self, admin: OperatorContext, body: StageRequest) -> MatrixVersionView:
        """A new pending version, numbered after the last; a shape it may not
        have is `ValidationFailed`."""
        ...

    @abstractmethod
    async def publish(self, admin: OperatorContext, number: int) -> MatrixVersionView:
        """The pending version `number`, published: `ValidationFailed` naming
        every reason it may not be."""
        ...

    @abstractmethod
    async def get_version(self, admin: OperatorContext, number: int | None) -> MatrixVersionView:
        """The version `number`, or, for None, the latest published."""
        ...
