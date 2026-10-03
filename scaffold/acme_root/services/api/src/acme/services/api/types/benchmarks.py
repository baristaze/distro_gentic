"""Wire types of the platform's benchmarks, as an operator reads them: a
scenario's runs, the newest first, which is its trend, and one run with
every trial."""

from datetime import datetime
from uuid import UUID

from acme.om.benchmarks.types.benchmark import Arm
from acme.services.api.types.common import View
from acme.services.api.types.matrix import FillView


class RoleFillView(View):
    role: str
    fill: FillView
    fallbacks: list[FillView]


class ContenderView(View):
    """What an arm's sessions ran: the agent kind, its version, and each model
    role's fill."""

    kind: str
    kind_version: int
    fills: list[RoleFillView]


class ArmResultView(View):
    """One arm's result: its trials, how many passed, the mean of their
    scores, and the sum of their costs."""

    trials: int
    passed: int
    score: float
    cost_micros: int


class TrialView(View):
    """One trial: its arm, its session, where and when it ran, its cost, and
    what its acceptance verdict found."""

    arm: Arm
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
    candidate: ContenderView
    baseline: ContenderView
    candidate_result: ArmResultView
    baseline_result: ArmResultView
    regressed: bool
    recorded_by: UUID


class BenchmarkView(BenchmarkSummaryView):
    """One run of a scenario, with every trial of both arms."""

    trials: list[TrialView]
