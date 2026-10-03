"""The matrix service: what a tenant on its own keys may choose and its
choices, and the operator's stage, publish, and read of a version, and its
record of a benchmark result and of a retired model."""

from abc import ABC, abstractmethod

from acme.om.context import OperatorContext, TenantContext
from acme.om.models.types.fill import ModelRole
from acme.services.api.types.matrix import (
    BenchmarkResultRequest,
    BenchmarkResultView,
    ChooseRequest,
    FillChoiceView,
    FillOptionsView,
    MatrixVersionView,
    RetirementView,
    RetireRequest,
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

    @abstractmethod
    async def record_result(
        self, admin: OperatorContext, body: BenchmarkResultRequest
    ) -> BenchmarkResultView:
        """What a benchmark run showed of a model for a model role; the
        latest result for the two decides whether a version serving the
        role with the model may be published."""
        ...

    @abstractmethod
    async def retire(self, admin: OperatorContext, body: RetireRequest) -> RetirementView:
        """The model, retired; a model retired already answers its first
        record."""
        ...
