"""Wire types of the model matrix: a fill as the API takes and shows it, a
version an operator stages and publishes, a benchmark result and a
retirement an operator records, and what a tenant on its own keys may
choose and has chosen."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from acme.integrations.model_providers.types import Effort, ProviderName
from acme.om.attribution.types.principal import MAX_KIND
from acme.om.matrix.types.matrix import MAX_FILLS, MAX_ROLES, MAX_ROWS, NAME, MatrixStatus
from acme.om.matrix.types.record import MAX_MODEL, BenchmarkName
from acme.om.models.types.fill import ModelRole, OutputShape
from acme.services.api.types.common import RequestBody, View

Name = Annotated[str, StringConstraints(pattern=NAME)]
KindName = Annotated[str, StringConstraints(min_length=1, max_length=MAX_KIND)]


class EligibilityBody(RequestBody):
    """What a fill offers: zero data retention, a region."""

    zero_retention: bool = False
    region: str | None = Field(default=None, min_length=1, max_length=64)


class FillBody(RequestBody):
    """A fill: a provider's model, how hard it works, its output bound and
    shape, its context window, and what it offers. The output bound fits
    inside the window, and a schema is named exactly when the output is one.
    An output left out is text, and an eligibility left out offers
    nothing."""

    provider: ProviderName
    model: str = Field(min_length=1, max_length=200)
    effort: Effort | None = None
    thinking_budget: int | None = Field(default=None, gt=0)
    max_output_tokens: int = Field(gt=0)
    output: OutputShape | None = None
    schema_name: str | None = Field(default=None, min_length=1, max_length=200)
    context_window: int = Field(gt=0)
    eligibility: EligibilityBody | None = None


class EligibilityView(View):
    zero_retention: bool
    region: str | None


class FillView(View):
    provider: ProviderName
    model: str
    effort: Effort | None
    thinking_budget: int | None
    max_output_tokens: int
    output: OutputShape
    schema_name: str | None
    context_window: int
    eligibility: EligibilityView


class MatrixKeyBody(RequestBody):
    """What a row answers: each key it names must equal the question's, and a
    key left out matches every value. The row that names none matches every
    question."""

    environment: Name | None = None
    role: ModelRole | None = None
    kind: KindName | None = None
    plan_tier: Name | None = None
    workload: Name | None = None


class MatrixRowBody(RequestBody):
    """A row: the questions it matches, and its fills, the first the fill and
    the rest the fallbacks, each named once. A row that names no match
    matches every question."""

    matches: MatrixKeyBody | None = None
    fills: list[FillBody] = Field(min_length=1, max_length=MAX_FILLS)


class StageRequest(RequestBody):
    """A new version of the matrix: the model roles it serves and its rows,
    one a key. It is checked whole when it is published."""

    roles: list[ModelRole] = Field(min_length=1, max_length=MAX_ROLES)
    rows: list[MatrixRowBody] = Field(min_length=1, max_length=MAX_ROWS)


class MatrixKeyView(View):
    environment: str | None
    role: str | None
    kind: str | None
    plan_tier: str | None
    workload: str | None


class MatrixRowView(View):
    """A row: the questions it matches, the row's key, and its fills."""

    matches: MatrixKeyView = Field(validation_alias="key")
    fills: list[FillView]


class MatrixVersionView(View):
    """A version: pending until an operator publishes it, and the matrix from
    then until the next is published. Its rows never change."""

    id: UUID
    number: int
    roles: list[str]
    rows: list[MatrixRowView]
    status: MatrixStatus
    created_at: datetime
    created_by: UUID
    published_at: datetime | None
    published_by: UUID | None


class BenchmarkResultRequest(RequestBody):
    """What a benchmark run showed of a model for a model role: whether it
    passed, and where its evidence is (`run`, such as the run's id or its
    report's address). The latest result for the model and the role decides
    whether a version that serves the role with the model may be
    published."""

    provider: ProviderName
    model: str = Field(min_length=1, max_length=MAX_MODEL)
    role: ModelRole
    benchmark: BenchmarkName
    passed: bool
    run: str = Field(min_length=1, max_length=500)


class BenchmarkResultView(View):
    """A recorded result, written once."""

    id: UUID
    provider: ProviderName
    model: str
    role: str
    benchmark: str
    passed: bool
    run: str
    created_at: datetime
    recorded_by: UUID


class RetireRequest(RequestBody):
    """A model its provider retired, by name, as a fill names it."""

    provider: ProviderName
    model: str = Field(min_length=1, max_length=MAX_MODEL)


class RetirementView(View):
    """A retired model: no session resolves to it again, and a version that
    names it is not published. Recorded once a model."""

    id: UUID
    provider: ProviderName
    model: str
    created_at: datetime
    recorded_by: UUID


class FillOptionsView(View):
    """What a tenant on its own keys may choose for one model role: the fills
    the published matrix qualified for it, from a provider it holds a live
    key for."""

    role: str
    fills: list[FillView]


class ChooseRequest(RequestBody):
    """The fill a tenant chooses for a model role: one of that role's
    options."""

    fill: FillBody


class FillChoiceView(View):
    """The tenant's choice for one model role, from its next session on."""

    id: UUID
    role: str
    fill: FillView
    created_at: datetime
    updated_at: datetime
    updated_by: UUID
