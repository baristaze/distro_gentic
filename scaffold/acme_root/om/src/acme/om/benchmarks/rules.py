"""Pure rules of benchmarks: the order a contender's trials take beside the
other's, whether a run kept it, what each contender's trials show, whether the
candidate regressed, and what a benchmark tells the model matrix. Values
in, values out."""

from collections.abc import Sequence

from acme.om.benchmarks.types.benchmark import Benchmark, Contender, ContenderResult, Trial
from acme.om.matrix.types.record import BenchmarkRun


def schedule(pairs: int) -> tuple[Contender, ...]:
    """The order a run takes `pairs` trials of each contender in, on one executor:
    candidate, baseline, baseline, candidate, and again. Neither contender runs
    two ahead of the other, and a drift that grows steadily over the run
    falls on both alike."""
    order: list[Contender] = []
    for pair in range(pairs):
        first, second = (
            (Contender.CANDIDATE, Contender.BASELINE)
            if pair % 2 == 0
            else (
                Contender.BASELINE,
                Contender.CANDIDATE,
            )
        )
        order.extend((first, second))
    return tuple(order)


def interleaving_refusal(trials: Sequence[Trial]) -> str | None:
    """Why the trials are no fair comparison: a contender with no trial, contenders
    with different counts, more than one executor, or one contender run ahead of
    the other, as a block run before the other is. Read in the order the
    trials started, no point holds two more of one contender than of the other."""
    counts = {
        contender: sum(1 for trial in trials if trial.contender is contender)
        for contender in Contender
    }
    if not all(counts.values()):
        return "a benchmark runs trials of both the candidate and the baseline"
    if counts[Contender.CANDIDATE] != counts[Contender.BASELINE]:
        return (
            "the contenders ran different counts of trials: "
            f"{counts[Contender.CANDIDATE]} and {counts[Contender.BASELINE]}"
        )
    executors = sorted({trial.executor for trial in trials})
    if len(executors) > 1:
        return f"the candidate and the baseline ran on more than one executor: {executors}"
    ahead = 0
    for trial in sorted(trials, key=lambda found: found.started_at):
        ahead += 1 if trial.contender is Contender.CANDIDATE else -1
        if abs(ahead) > 1:
            return "the candidate and the baseline ran in blocks, not interleaved"
    return None


def contender_result(trials: Sequence[Trial], contender: Contender) -> ContenderResult:
    """What one contender's trials show: every trial counted, none dropped."""
    own = [trial for trial in trials if trial.contender is contender]
    return ContenderResult(
        trials=len(own),
        passed=sum(1 for trial in own if trial.passed),
        score=sum(trial.score for trial in own) / len(own),
        cost_micros=sum(trial.cost_micros for trial in own),
    )


def regressed(candidate: ContenderResult, baseline: ContenderResult) -> bool:
    """A candidate that scored under its baseline regressed."""
    return candidate.score < baseline.score


def qualifications(benchmark: Benchmark, run: str) -> tuple[BenchmarkRun, ...]:
    """What a benchmark shows the model matrix: for each model role whose
    fill the candidate changed, whether its model held up against the
    baseline's on the scenario. It passed when the candidate did not
    regress. Each cites `run`, where the benchmark's export is kept: the
    benchmark job's run, which holds it as an artifact. Only a run whose
    contenders ran one agent kind at one version says anything of a model: when
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
