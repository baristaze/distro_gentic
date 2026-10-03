"""A benchmark keeps every trial of a scenario, each arm pinned to the
agent kind, its version, and the fill set that produced it, with the
verdict that judged it, its score, and its cost; candidate and baseline
trials interleave on one executor; and a candidate that scores under its
baseline is flagged."""

import pytest
from contracts.benchmark_storage import BASELINE, CANDIDATE, make_trials, operator

from acme.om.benchmarks.impl.manager import BenchmarksManagerImpl
from acme.om.benchmarks.rules import interleaving_refusal, qualifications, schedule
from acme.om.benchmarks.storage.impl.memory import BenchmarkStorageMemoryImpl
from acme.om.benchmarks.types.benchmark import Arm, BenchmarkTrials
from acme.om.context import OperatorRole
from acme.om.exceptions import NotAuthorized, NotFound, ValidationFailed

WHOLE, NOTHING = 0, 7
"""Links a trial's chain lacks: none, or all seven."""

RUN = "https://github.com/acme/acme/actions/runs/1"
"""The benchmark job's run its export is kept with."""


@pytest.fixture
def benchmarks() -> BenchmarksManagerImpl:
    return BenchmarksManagerImpl(BenchmarkStorageMemoryImpl())


# Check 2: stored with what produced it, and a regression flagged.


async def test_a_run_is_stored_with_its_fill_set_kind_version_score_and_cost(
    benchmarks: BenchmarksManagerImpl,
) -> None:
    admin = operator()
    run = make_trials([WHOLE, NOTHING], [WHOLE, WHOLE], cost_micros=250_000)
    recorded = await benchmarks.record(admin, run)
    stored = await benchmarks.get(admin, recorded.id)
    assert stored == recorded
    assert (stored.candidate, stored.baseline) == (CANDIDATE, BASELINE)
    assert stored.candidate.fills[0].fill.model == "claude-opus-5-5"
    assert (stored.candidate.kind, stored.candidate.kind_version) == ("engineer", 2)
    assert (stored.candidate_result.score, stored.candidate_result.passed) == (0.5, 1)
    assert stored.candidate_result.cost_micros == stored.baseline_result.cost_micros == 500_000
    # Every trial is preserved, each with the whole verdict that judged it.
    assert stored.trials == run.trials
    assert all(trial.verdict.session_id == trial.session_id for trial in stored.trials)
    assert stored.recorded_by == admin.identity_id


async def test_a_lower_score_than_its_baseline_is_flagged(
    benchmarks: BenchmarksManagerImpl,
) -> None:
    admin = operator()
    lower = await benchmarks.record(admin, make_trials([WHOLE, NOTHING], [WHOLE, WHOLE]))
    assert lower.regressed
    assert (lower.candidate_result.score, lower.baseline_result.score) == (0.5, 1.0)
    level = await benchmarks.record(admin, make_trials([WHOLE, NOTHING], [NOTHING, WHOLE]))
    higher = await benchmarks.record(admin, make_trials([WHOLE, WHOLE], [NOTHING, WHOLE]))
    assert not level.regressed and not higher.regressed
    # One link short in one trial is a lower score too.
    short = await benchmarks.record(admin, make_trials([WHOLE, 1], [WHOLE, WHOLE]))
    assert short.regressed and short.candidate_result.score == pytest.approx(1 - 1 / 14)
    history = await benchmarks.history(admin, "orders-vanish", 10)
    assert [found.id for found in history] == [short.id, higher.id, level.id, lower.id]


async def test_a_benchmark_qualifies_the_model_it_changed_for_the_matrix(
    benchmarks: BenchmarksManagerImpl,
) -> None:
    admin = operator()
    held = await benchmarks.record(admin, make_trials([WHOLE, WHOLE], [WHOLE, WHOLE]))
    (run,) = qualifications(held, RUN)
    assert (run.ref.name, run.role, run.benchmark) == (
        "anthropic/claude-opus-5-5",
        "main",
        "orders-vanish",
    )
    assert run.passed and run.run == f"{RUN}, benchmark {held.id}"
    lower = await benchmarks.record(admin, make_trials([WHOLE, NOTHING], [WHOLE, WHOLE]))
    assert [found.passed for found in qualifications(lower, RUN)] == [False]
    # A run that changed only the kind's version says nothing of a model.
    kind_only = CANDIDATE.model_copy(update={"fills": BASELINE.fills, "kind_version": 3})
    same = make_trials([WHOLE], [WHOLE]).model_copy(update={"candidate": kind_only})
    assert qualifications(await benchmarks.record(admin, same), RUN) == ()


async def test_a_run_that_changed_the_kind_beside_the_model_qualifies_nothing(
    benchmarks: BenchmarksManagerImpl,
) -> None:
    # The model changed, and so did the kind's version, or the kind: a
    # score either way could be either's, so neither credits nor blames it.
    admin = operator()
    for moved in ({"kind_version": 3}, {"kind": "reviewer"}):
        candidate = CANDIDATE.model_copy(update=moved)
        for broken in (WHOLE, NOTHING):
            run = make_trials([broken], [WHOLE]).model_copy(update={"candidate": candidate})
            assert qualifications(await benchmarks.record(admin, run), RUN) == ()


# The arms interleave on one executor.


def test_the_schedule_interleaves_the_arms() -> None:
    assert schedule(2) == (Arm.CANDIDATE, Arm.BASELINE, Arm.BASELINE, Arm.CANDIDATE)
    assert interleaving_refusal(make_trials([WHOLE] * 6, [WHOLE] * 6).trials) is None


BLOCKS = (Arm.CANDIDATE, Arm.CANDIDATE, Arm.BASELINE, Arm.BASELINE)
UNEVEN = (Arm.CANDIDATE, Arm.BASELINE, Arm.CANDIDATE, Arm.CANDIDATE)


@pytest.mark.parametrize(
    ("run", "words"),
    [
        (make_trials([WHOLE] * 2, [WHOLE] * 2, order=BLOCKS), "in blocks, not interleaved"),
        (make_trials([WHOLE] * 3, [WHOLE], order=UNEVEN), "different counts"),
        (
            make_trials([WHOLE] * 2, [], order=(Arm.CANDIDATE, Arm.CANDIDATE)),
            "both the candidate and the baseline",
        ),
    ],
)
async def test_trials_that_do_not_interleave_are_refused(
    benchmarks: BenchmarksManagerImpl, run: BenchmarkTrials, words: str
) -> None:
    admin = operator()
    with pytest.raises(ValidationFailed, match=words):
        await benchmarks.record(admin, run)
    assert await benchmarks.history(admin, "orders-vanish", 10) == ()


async def test_trials_on_two_executors_are_refused(benchmarks: BenchmarksManagerImpl) -> None:
    run = make_trials([WHOLE], [WHOLE])
    moved = (run.trials[0], run.trials[1].model_copy(update={"executor": "executor-2"}))
    with pytest.raises(ValidationFailed, match="more than one executor"):
        await benchmarks.record(operator(), run.model_copy(update={"trials": moved}))


async def test_only_an_operator_with_write_records_one(benchmarks: BenchmarksManagerImpl) -> None:
    reader = operator(OperatorRole.READ)
    run = make_trials([WHOLE], [WHOLE])
    with pytest.raises(NotAuthorized):
        await benchmarks.record(reader, run)
    with pytest.raises(NotFound):
        await benchmarks.get(reader, run.trials[0].session_id)
