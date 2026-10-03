"""The operators' reads of the platform's benchmarks under
/v1/admin/benchmarks: a scenario's runs, the newest first, which is its
trend, and one run with every trial. Each takes `OperatorContext` and the
read permission; a benchmark belongs to no tenant."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from acme.om.evidence.types.record import NAME
from acme.services.api.gateway.admin import OperatorCtx
from acme.services.api.gateway.resolve import BenchmarksService
from acme.services.api.types.benchmarks import BenchmarkSummaryView, BenchmarkView
from acme.services.api.types.common import LIMIT_DEFAULT

router = APIRouter(prefix="/admin/benchmarks", tags=["admin"])


@router.get("", response_model=list[BenchmarkSummaryView])
async def get_trend(
    admin: OperatorCtx,
    service: BenchmarksService,
    scenario: Annotated[str, Query(pattern=NAME)],
    limit: int = LIMIT_DEFAULT,
) -> list[BenchmarkSummaryView]:
    """The scenario's runs, the newest first: each arm's score and cost, and
    whether the candidate regressed."""
    return await service.get_trend(admin, scenario, limit)


@router.get("/{benchmark_id}", response_model=BenchmarkView)
async def get_benchmark(
    admin: OperatorCtx, service: BenchmarksService, benchmark_id: UUID
) -> BenchmarkView:
    return await service.get_benchmark(admin, benchmark_id)
