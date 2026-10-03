"""The benchmarks service: an operator reads a scenario's runs, which is its
trend, and one run with every trial."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import OperatorContext
from acme.services.api.types.benchmarks import BenchmarkSummaryView, BenchmarkView


class BenchmarksServiceInterface(ABC):
    @abstractmethod
    async def get_trend(
        self, admin: OperatorContext, scenario: str, limit: int
    ) -> list[BenchmarkSummaryView]:
        """The scenario's runs, the newest first, without their trials."""
        ...

    @abstractmethod
    async def get_benchmark(self, admin: OperatorContext, benchmark_id: UUID) -> BenchmarkView: ...
