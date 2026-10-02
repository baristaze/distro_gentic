"""The matrix swimlane: which model serves which question, as the platform
publishes it, and what a tenant may choose within it.

The platform's operators write the matrix as pending versions and publish
one when every fill in it is priced and qualified, and a row matches every
question. They record what a benchmark run showed of a model for a model
role, and the models their providers retire. A tenant never names a model,
unless it pays its providers on its own keys: then it may choose, for a
model role, among the fills the matrix qualified for that role, from a
provider it holds a key for."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from acme.om.context import OperatorContext, TenantContext
from acme.om.matrix.types.matrix import MatrixRow, MatrixVersion
from acme.om.matrix.types.record import BenchmarkResult, BenchmarkRun, ModelRef, Retirement
from acme.om.matrix.types.tenant import FillOverride, MatrixPin
from acme.om.models.types.fill import Fill, ModelRole


class MatrixOperatorManagerInterface(ABC):
    @abstractmethod
    async def stage(
        self, admin: OperatorContext, roles: Sequence[ModelRole], rows: Sequence[MatrixRow]
    ) -> MatrixVersion:
        """Writes a new pending version, numbered after the last, as it is:
        an edit of the matrix is a new version, and no version changes once
        written. Its shape is checked here (`ValidationFailed`), its fills
        when it is published."""
        ...

    @abstractmethod
    async def publish(self, admin: OperatorContext, number: int) -> MatrixVersion:
        """Publishes the pending version `number`, which every session
        resolved from then on is pinned to; a running session keeps the
        version it holds. `ValidationFailed` naming every reason it may not:
        no row matches every question, or a fill has no price row of its own,
        no passing benchmark for a model role its row serves, or a retired
        model. `PreconditionFailed` when it is not pending, or a later one is
        published."""
        ...

    @abstractmethod
    async def get_version(self, admin: OperatorContext, number: int | None) -> MatrixVersion:
        """The version `number`, or, for None, the latest published;
        `NotFound` when there is none."""
        ...

    @abstractmethod
    async def record_benchmark(self, admin: OperatorContext, run: BenchmarkRun) -> BenchmarkResult:
        """Records what a benchmark run showed of a model for a model role.
        The latest result for the two decides whether a version that serves
        the role with the model may be published; no code change waits on
        it."""
        ...

    @abstractmethod
    async def retire_model(self, admin: OperatorContext, model: ModelRef) -> Retirement:
        """Records that the provider retired `model`: no session resolves to
        it again, and each session on it switches at the start of its next
        loop. Recorded once; a second record answers the first."""
        ...


class MatrixManagerInterface(ABC):
    @abstractmethod
    async def get_pin(self, ctx: TenantContext, session_id: UUID) -> MatrixPin:
        """The version of the matrix the session's fills came from last;
        `NotFound` before its fills are resolved."""
        ...

    @abstractmethod
    async def choose_fill(self, ctx: TenantContext, role: ModelRole, fill: Fill) -> FillOverride:
        """The tenant's own choice of fill for `role`, from its next session
        on, as one who writes the tenant's configuration may. Refused
        (`ValidationFailed`) unless the tenant pays its providers on its own
        keys, holds a live key for the fill's provider, and the published
        matrix qualified the fill for the role."""
        ...

    @abstractmethod
    async def drop_choice(self, ctx: TenantContext, role: ModelRole) -> bool:
        """The tenant's choice for `role` is taken away, and the matrix
        answers the role again; False when there was none."""
        ...

    @abstractmethod
    async def get_choices(self, ctx: TenantContext) -> tuple[FillOverride, ...]:
        """The tenant's choices, by model role."""
        ...
