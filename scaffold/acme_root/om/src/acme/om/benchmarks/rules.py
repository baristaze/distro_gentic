"""Pure rules of benchmarks: the order an arm's trials take beside the
other's, whether a run kept it, what each arm's trials show, whether the
candidate regressed, and what a benchmark tells the model matrix. Values
in, values out."""

from collections.abc import Sequence

from acme.om.benchmarks.types.benchmark import Arm, ArmResult, Benchmark, Trial
from acme.om.matrix.types.record import BenchmarkRun


def schedule(pairs: int) -> tuple[Arm, ...]:
    """The order a run takes `pairs` trials of each arm in, on one executor:
    candidate, baseline, baseline, candidate, and again. Neither arm runs
    two ahead of the other, and a drift that grows steadily over the run
    falls on both alike."""
    order: list[Arm] = []
    for pair in range(pairs):
        first, second = (
            (Arm.CANDIDATE, Arm.BASELINE)
            if pair % 2 == 0
            else (
                Arm.BASELINE,
                Arm.CANDIDATE,
            )
        )
        order.extend((first, second))
    return tuple(order)


def interleaving_refusal(trials: Sequence[Trial]) -> str | None:
    """Why the trials are no fair comparison: an arm with no trial, arms
    with different counts, more than one executor, or one arm run ahead of
    the other, as a block run before the other is. Read in the order the
    trials started, no point holds two more of one arm than of the other."""
    counts = {arm: sum(1 for trial in trials if trial.arm is arm) for arm in Arm}
    if not all(counts.values()):
        return "a benchmark runs trials of both the candidate and the baseline"
    if counts[Arm.CANDIDATE] != counts[Arm.BASELINE]:
        return f"the arms ran different counts of trials: {counts[Arm.CANDIDATE]} and {counts[Arm.BASELINE]}"
    executors = sorted({trial.executor for trial in trials})
    if len(executors) > 1:
        return f"the candidate and the baseline ran on more than one executor: {executors}"
    ahead = 0
    for trial in sorted(trials, key=lambda found: found.started_at):
        ahead += 1 if trial.arm is Arm.CANDIDATE else -1
        if abs(ahead) > 1:
            return "the candidate and the baseline ran in blocks, not interleaved"
    return None


def arm_result(trials: Sequence[Trial], arm: Arm) -> ArmResult:
    """What one arm's trials show: every trial counted, none dropped."""
    own = [trial for trial in trials if trial.arm is arm]
    return ArmResult(
        trials=len(own),
        passed=sum(1 for trial in own if trial.passed),
        score=sum(trial.score for trial in own) / len(own),
        cost_micros=sum(trial.cost_micros for trial in own),
    )


def regressed(candidate: ArmResult, baseline: ArmResult) -> bool:
    """A candidate that scored under its baseline regressed."""
    return candidate.score < baseline.score


def qualifications(benchmark: Benchmark, run: str) -> tuple[BenchmarkRun, ...]:
    """What a benchmark shows the model matrix: for each model role whose
    fill the candidate changed, whether its model held up against the
    baseline's on the scenario. It passed when the candidate did not
    regress. Each cites `run`, where the benchmark's export is kept: the
    benchmark job's run, which holds it as an artifact. Only a run whose
    arms ran one agent kind at one version says anything of a model: when
    the kind or its version changed too, the score is either's, and it
    qualifies nothing."""
    candidate, baseline = benchmark.candidate, benchmark.baseline
    if (candidate.kind, candidate.kind_version) != (baseline.kind, baseline.kind_version):
        return ()
    before = {found.role: found.fill for found in baseline.fills}
    return tuple(
        BenchmarkRun(
            provider=found.fill.provider,
            model=found.fill.model,
            role=found.role,
            benchmark=benchmark.scenario,
            passed=not benchmark.regressed,
            run=f"{run}, benchmark {benchmark.id}",
        )
        for found in candidate.fills
        if before.get(found.role) != found.fill
    )
