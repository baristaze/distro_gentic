"""What the platform's operators record of a model, apart from any version
of the matrix: a benchmark's result for a model role, and the provider's
retirement of a model. Both are written once and never changed."""

from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from acme.integrations.model_providers.types import ProviderName
from acme.om.base import Created, Identifiable, Platform
from acme.om.models.types.fill import Fill, ModelRole

MAX_MODEL = 200

BenchmarkName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,99}$")]


class ModelRef(Platform):
    """A provider's model, by name, as a fill names it."""

    provider: ProviderName
    model: str = Field(min_length=1, max_length=MAX_MODEL)

    @staticmethod
    def of(fill: Fill) -> ModelRef:
        return ModelRef(provider=fill.provider, model=fill.model)

    @property
    def name(self) -> str:
        return f"{self.provider.value}/{self.model}"


class BenchmarkRun(Platform):
    """What a person records of one benchmark run: the model, the model role
    it was run for, the benchmark, whether it passed, and where its evidence
    is (`run`, a reference such as the run's id or its report's address)."""

    provider: ProviderName
    model: str = Field(min_length=1, max_length=MAX_MODEL)
    role: ModelRole
    benchmark: BenchmarkName
    passed: bool
    run: str = Field(min_length=1, max_length=500)

    @property
    def ref(self) -> ModelRef:
        return ModelRef(provider=self.provider, model=self.model)


class BenchmarkResult(BenchmarkRun, Identifiable, Created):
    """A recorded run. The latest result for a model and a model role decides
    whether the model may serve that role."""

    recorded_by: UUID  # the operator's identity


class Retirement(Identifiable, Created):
    """A model its provider retired: no session resolves to it again, and a
    session on it switches at its next loop."""

    provider: ProviderName
    model: str = Field(min_length=1, max_length=MAX_MODEL)
    recorded_by: UUID  # the operator's identity

    @property
    def ref(self) -> ModelRef:
        return ModelRef(provider=self.provider, model=self.model)
