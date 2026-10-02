"""A benchmark keeps every trial of a scenario, each arm pinned to the
agent kind, its version, and the fill set that produced it, with its
judged score and its cost; candidate and baseline trials interleave on
one station; and a candidate that scores under its baseline is flagged."""

import pytest
from contracts.benchmark_storage import BASELINE, CANDIDATE, make_trials, operator

from acme.om.benchmarks.impl.manager import BenchmarksManagerImpl
from acme.om.benchmarks.rules import interleaving_refusal, qualifications, schedule
from acme.om.benchmarks.storage.impl.memory import BenchmarkStorageMemoryImpl
from acme.om.benchmarks.types.benchmark import Arm
from acme.om.context import OperatorRole
from acme.om.exceptions import NotAuthorized, NotFound, ValidationFailed


@pytest.fixture
def benchmarks() -> BenchmarksManagerImpl:
    return BenchmarksManagerImpl(BenchmarkStorageMemoryImpl())


# Check 2: stored with what produced it, and a regression flagged.


async def test_a_run_is_stored_with_its_fill_set_kind_version_score_and_cost(
    benchmarks: BenchmarksManagerImpl,
) -> None:
    admin = operator()
    run = make_trials([1.0, 0.5], [1.0, 1.0], cost_micros=250_000)
    recorded = await benchmarks.record(admin, run)
    stored = await benchmarks.get(admin, recorded.id)
    assert stored == recorded
    assert (stored.candidate, stored.baseline) == (CANDIDATE, BASELINE)
    assert stored.candidate.fills[0].fill.model == "claude-opus-5-5"
    assert (stored.candidate.kind, stored.candidate.kind_version) == ("engineer", 2)
    assert (stored.candidate_result.score, stored.candidate_result.passed) == (0.75, 1)
    assert stored.candidate_result.cost_micros == stored.baseline_result.cost_micros == 500_000
    # Every trial is preserved, with the session and the verdict that judged it.
    assert stored.trials == run.trials
    assert stored.recorded_by == admin.identity_id


async def test_a_lower_score_than_its_baseline_is_flagged(
    benchmarks: BenchmarksManagerImpl,
) -> None:
    admin = operator()
    lower = await benchmarks.record(admin, make_trials([1.0, 0.0], [1.0, 1.0]))
    assert lower.regressed
    assert (lower.candidate_result.score, lower.baseline_result.score) == (0.5, 1.0)
    level = await benchmarks.record(admin, make_trials([1.0, 0.0], [0.0, 1.0]))
    higher = await benchmarks.record(admin, make_trials([1.0, 1.0], [0.0, 1.0]))
    assert not level.regressed and not higher.regressed
    history = await benchmarks.history(admin, "grip-slips", 10)
    assert [found.id for found in history] == [higher.id, level.id, lower.id]


async def test_a_benchmark_qualifies_the_model_it_changed_for_the_matrix(
    benchmarks: BenchmarksManagerImpl,
) -> None:
    admin = operator()
    held = await benchmarks.record(admin, make_trials([1.0, 1.0], [1.0, 1.0]))
    (run,) = qualifications(held)
    assert (run.ref.name, run.role, run.benchmark) == (
        "anthropic/claude-opus-5-5",
        "main",
        "grip-slips",
    )
    assert run.passed and run.run == f"benchmark {held.id}"
    lower = await benchmarks.record(admin, make_trials([1.0, 0.0], [1.0, 1.0]))
    assert [found.passed for found in qualifications(lower)] == [False]
    # A run that changed only the kind's version says nothing of a model.
    same = make_trials([1.0], [1.0]).model_copy(
        update={"candidate": CANDIDATE.model_copy(update={"fills": BASELINE.fills})}
    )
    assert qualifications(await benchmarks.record(admin, same)) == ()


# The arms interleave on one station.


def test_the_schedule_interleaves_the_arms() -> None:
    assert schedule(2) == (Arm.CANDIDATE, Arm.BASELINE, Arm.BASELINE, Arm.CANDIDATE)
    assert interleaving_refusal(make_trials([1.0] * 6, [1.0] * 6).trials) is None


@pytest.mark.parametrize(
    ("run", "words"),
    [
        (
            make_trials(
                [1.0, 1.0],
                [1.0, 1.0],
                order=(Arm.CANDIDATE, Arm.CANDIDATE, Arm.BASELINE, Arm.BASELINE),
            ),
            "in blocks, not interleaved",
        ),
        (
            make_trials(
                [1.0, 1.0, 1.0],
                [1.0],
                order=(Arm.CANDIDATE, Arm.BASELINE, Arm.CANDIDATE, Arm.CANDIDATE),
            ),
            "different counts",
        ),
        (
            make_trials([1.0, 1.0], [], order=(Arm.CANDIDATE, Arm.CANDIDATE)),
            "both the candidate and the baseline",
        ),
    ],
)
async def test_trials_that_do_not_interleave_are_refused(
    benchmarks: BenchmarksManagerImpl, run: object, words: str
) -> None:
    admin = operator()
    with pytest.raises(ValidationFailed, match=words):
        await benchmarks.record(admin, run)  # type: ignore[arg-type]
    assert await benchmarks.history(admin, "grip-slips", 10) == ()


async def test_trials_on_two_stations_are_refused(benchmarks: BenchmarksManagerImpl) -> None:
    run = make_trials([1.0], [1.0])
    moved = (run.trials[0], run.trials[1].model_copy(update={"station": "station-2"}))
    with pytest.raises(ValidationFailed, match="more than one station"):
        await benchmarks.record(operator(), run.model_copy(update={"trials": moved}))


async def test_only_an_operator_with_write_records_one(benchmarks: BenchmarksManagerImpl) -> None:
    reader = operator(OperatorRole.READ)
    with pytest.raises(NotAuthorized):
        await benchmarks.record(reader, make_trials([1.0], [1.0]))
    with pytest.raises(NotFound):
        await benchmarks.get(reader, make_trials([1.0], [1.0]).trials[0].session_id)
