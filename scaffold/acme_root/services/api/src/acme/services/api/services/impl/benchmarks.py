from uuid import UUID

from acme.om.benchmarks import BenchmarksManagerInterface
from acme.om.benchmarks.types.benchmark import Trial
from acme.om.context import OperatorContext
from acme.services.api.services.benchmarks import BenchmarksServiceInterface
from acme.services.api.types.benchmarks import BenchmarkSummaryView, BenchmarkView, TrialView


def trial_view(trial: Trial) -> TrialView:
    return TrialView(
        arm=trial.arm,
        session_id=trial.session_id,
        executor=trial.executor,
        started_at=trial.started_at,
        cost_micros=trial.cost_micros,
        verdict_id=trial.verdict.id,
        passed=trial.passed,
        score=trial.score,
        broken=sorted(link.value for link in trial.verdict.broken()),
    )


class BenchmarksServiceImpl(BenchmarksServiceInterface):
    def __init__(self, benchmarks: BenchmarksManagerInterface) -> None:
        self._benchmarks = benchmarks

    async def get_trend(
        self, admin: OperatorContext, scenario: str, limit: int
    ) -> list[BenchmarkSummaryView]:
        runs = await self._benchmarks.history(admin, scenario, limit)
        return [BenchmarkSummaryView.model_validate(run) for run in runs]

    async def get_benchmark(self, admin: OperatorContext, benchmark_id: UUID) -> BenchmarkView:
        run = await self._benchmarks.get(admin, benchmark_id)
        summary = BenchmarkSummaryView.model_validate(run)
        return BenchmarkView(
            **summary.model_dump(), trials=[trial_view(trial) for trial in run.trials]
        )
