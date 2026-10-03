import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.om.base import Platform, new_id, utcnow
from acme.om.benchmarks import rules
from acme.om.benchmarks.manager import BenchmarksManagerInterface
from acme.om.benchmarks.storage import BenchmarkStorageInterface
from acme.om.benchmarks.types.benchmark import Arm, Benchmark, BenchmarkTrials
from acme.om.context import OperatorContext, OperatorPermission
from acme.om.exceptions import NotFound, ValidationFailed

log = logging.getLogger(__name__)


class BenchmarksOptions(Platform):
    max_limit: int = 200  # benchmarks one read of a history holds


class BenchmarksManagerImpl(BenchmarksManagerInterface):
    """The operators' record of the benchmark job's runs: global rows, each
    written once by an operator who holds the plane's write."""

    def __init__(
        self,
        storage: BenchmarkStorageInterface,
        options: BenchmarksOptions | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._options = options or BenchmarksOptions()
        self._clock = clock

    async def record(self, admin: OperatorContext, run: BenchmarkTrials) -> Benchmark:
        admin.require(OperatorPermission.WRITE)
        refusal = rules.interleaving_refusal(run.trials)
        if refusal is not None:
            raise ValidationFailed(f"benchmark {run.scenario}: {refusal}")
        candidate = rules.arm_result(run.trials, Arm.CANDIDATE)
        baseline = rules.arm_result(run.trials, Arm.BASELINE)
        benchmark = Benchmark(
            **dict(run),
            id=new_id(),
            created_at=self._clock(),
            candidate_result=candidate,
            baseline_result=baseline,
            regressed=rules.regressed(candidate, baseline),
            recorded_by=admin.identity_id,
        )
        await self._storage.create_benchmark(benchmark)
        log.info(
            "operator %s recorded benchmark %s of %s: %.3f against %.3f%s",
            admin.identity_id,
            benchmark.id,
            run.scenario,
            candidate.score,
            baseline.score,
            ", a regression" if benchmark.regressed else "",
        )
        return benchmark

    async def get(self, admin: OperatorContext, benchmark_id: UUID) -> Benchmark:
        admin.require(OperatorPermission.READ)
        found = await self._storage.read_benchmark(benchmark_id)
        if found is None:
            raise NotFound(f"benchmark {benchmark_id} not found")
        return found

    async def history(
        self, admin: OperatorContext, scenario: str, limit: int
    ) -> tuple[Benchmark, ...]:
        admin.require(OperatorPermission.READ)
        bounded = max(1, min(limit, self._options.max_limit))
        return tuple(await self._storage.read_history(scenario, bounded))
