# Benchmarks

What an acceptance scenario showed of a candidate against its baseline.
Benchmarks follow from [acceptance](../evidence/README.md): each trial is
a session the harness judged. This is one of the kinds of thing [Acme is
made of](../../../../README.md).

## What it holds

- **Contender**: what an arm's sessions run: the agent kind, its
  version, and the fill set, each model role's fill.
- **Trial**: one preserved run of the scenario: its arm, its session, the
  station it ran on, the acceptance verdict that judged it, its judged
  score, and its cost.
- **Benchmark**: one run of a scenario: the candidate, the baseline,
  every trial of both, each arm's score and cost, and whether the
  candidate regressed. It is written once and never changed.

## What can happen

- **Record.** An operator records a run from the benchmark job. The
  scores, the costs, and the flag are computed here from the trials,
  never taken from the caller.
- **Read** one, or a scenario's history, the newest first.

## The rules

- **The arms interleave on one station.** Trials run candidate,
  baseline, baseline, candidate, and again. A run whose arms ran in
  blocks, on two stations, or in different counts is refused.
- **Every trial counts.** An arm's score is the mean of its trials'
  judged scores, and its cost their sum. None is dropped.
- **A lower score is a regression.** A candidate that scores under its
  baseline is flagged.
- **Pinned to what produced it.** Each arm names its agent kind, its
  version, and its fill set.
- **No gate waits on it.** The benchmark job runs on a person's
  dispatch, never on a push or a pull request.
- **The platform's own.** A benchmark belongs to no tenant, and nothing
  purges it.
- **It feeds the matrix.** For each model role whose fill the candidate
  changed, the run passed the model when the candidate did not regress
  (`rules.qualifications`).

<!-- agents-only
The pure rules are `rules.py`: `schedule` gives the order, and
`interleaving_refusal` holds it. A trial's score is the acceptance
verdict's `score`, the share of the chain's links held. The rehearsal
in `om/tests/benchmark/` is the shape of a scenario's case; ADR 2018
records the decisions.
-->

## How another namespace composes it

The benchmark job runs a scenario's trials through the acceptance
harness of the [evidence](../evidence/README.md), hands the run to
`record`, and records what it shows of each model it changed with the
[model matrix](../matrix/README.md): a model whose candidate did not
regress has passed the scenario for its model role. That result is what
qualifies the model for a version of the matrix.
