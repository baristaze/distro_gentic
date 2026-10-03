"""The benchmarks swimlane: what each run of an acceptance scenario showed
of a candidate against its baseline, kept for good. The platform's
operators record them from the benchmark job, which no gate a code change
needs waits on; a benchmark belongs to no tenant."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.benchmarks.types.benchmark import Benchmark, BenchmarkTrials
from acme.om.context import OperatorContext


class BenchmarksManagerInterface(ABC):
    @abstractmethod
    async def record(self, admin: OperatorContext, run: BenchmarkTrials) -> Benchmark:
        """Keeps a run of a scenario, written once: its arms, every trial, each
        arm's score and cost, and whether the candidate regressed, all
        computed here from the trials. Refused (`ValidationFailed`) unless the
        candidate's and the baseline's trials interleave on one station.
        Needs the operators' write."""
        ...

    @abstractmethod
    async def get(self, admin: OperatorContext, benchmark_id: UUID) -> Benchmark:
        """One benchmark; `NotFound` when there is none."""
        ...

    @abstractmethod
    async def history(
        self, admin: OperatorContext, scenario: str, limit: int
    ) -> tuple[Benchmark, ...]:
        """The scenario's benchmarks, the newest first; `limit` is clamped."""
        ...
