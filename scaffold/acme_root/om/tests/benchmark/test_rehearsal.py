"""The benchmark job's rehearsal: an acceptance scenario's trials, a
candidate and a baseline interleaved on one station, each judged by the
harness and recorded over the stack as a benchmark, written once, and
what it shows of the model the candidate changed recorded with the model
matrix.

Scripted sessions stand in for the agent and the executor is a
twin, so the rehearsal spends nothing and proves the job's wiring end to
end. A product adds its own scenarios beside it, its agents on real
providers. `make benchmark` runs it, and no gate a code change needs
does. It needs a migrated stack (`make migrate`), and keeps what it
records: no case here empties a table."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from contracts.acceptance import EXPORT, judged_trials
from contracts.benchmark_storage import BASELINE, CANDIDATE, operator
from contracts.rehearsal import world_over

from acme.om.benchmarks.rules import qualifications
from acme.om.benchmarks.types.benchmark import BenchmarkTrials
from acme.om.matrix.root import MatrixLayer
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings

pytestmark = pytest.mark.benchmark

PAIRS = 2
"""Trials of each arm: candidate, baseline, baseline, candidate."""


@pytest.fixture
async def storage(
    migration_settings: MigrationSettings, migrated: object
) -> AsyncIterator[StoragePostgresImpl]:
    root = StoragePostgresImpl(
        migration_settings.role_urls(),
        migration_settings.role_pools(),
        system_urls=migration_settings.system_role_urls(),
    )
    yield root
    await root.close()


async def test_the_scenarios_trials_are_judged_and_recorded(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    world = await world_over(storage, tmp_path)
    trials = await judged_trials(world.parts, world.owner, PAIRS)
    run = BenchmarkTrials(
        scenario=EXPORT.name, candidate=CANDIDATE, baseline=BASELINE, trials=trials
    )
    admin = operator()
    recorded = await world.managers.benchmarks.record(admin, run)
    assert await world.managers.benchmarks.get(admin, recorded.id) == recorded
    assert recorded.candidate_result.trials == recorded.baseline_result.trials == PAIRS
    matrix = MatrixLayer(storage).build(world.managers).matrix_operator
    fed = [await matrix.record_benchmark(admin, run) for run in qualifications(recorded)]
    assert [(found.model, found.passed) for found in fed] == [("claude-opus-5-5", True)]
    print(
        f"\n{EXPORT.name}: candidate {recorded.candidate_result.score:.3f}"
        f" against baseline {recorded.baseline_result.score:.3f},"
        f" {'a regression' if recorded.regressed else 'no regression'}"
        f" (benchmark {recorded.id})"
    )
    assert not recorded.regressed
