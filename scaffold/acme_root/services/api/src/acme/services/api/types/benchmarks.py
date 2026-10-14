"""Wire types of the platform's benchmarks, as an operator reads them: a
scenario's runs, the newest first, which is its trend, and one run with
every trial."""

from datetime import datetime
from uuid import UUID

from acme.om.benchmarks.types.benchmark import Contender
from acme.services.api.types.common import View
from acme.services.api.types.matrix import FillView


class RoleFillView(View):
    role: str
    fill: FillView
    fallbacks: list[FillView]


class ContenderPinView(View):
    """What a contender's sessions ran: the agent kind, its version, and each model
    role's fill."""

    kind: str
    kind_version: int
    fills: list[RoleFillView]


class ContenderResultView(View):
    """One contender's result: its trials, how many passed, the mean of their
    scores, and the sum of their costs."""

    trials: int
    passed: int
    score: float
    cost_micros: int


class TrialView(View):
    """One trial: its contender, its session, where and when it ran, its cost, and
    what its acceptance verdict found."""

    contender: Contender
    session_id: UUID
    executor: str
    started_at: datetime
    cost_micros: int
    verdict_id: UUID
    passed: bool
    score: float
    broken: list[str]


class BenchmarkSummaryView(View):
    """One run of a scenario, without its trials: a point of the scenario's
    trend."""

    id: UUID
    scenario: str
    created_at: datetime
    candidate: ContenderPinView
    baseline: ContenderPinView
    candidate_result: ContenderResultView
    baseline_result: ContenderResultView
    regressed: bool
    recorded_by: UUID


class BenchmarkView(BenchmarkSummaryView):
    """One run of a scenario, with every trial of both contenders."""

    trials: list[TrialView]
