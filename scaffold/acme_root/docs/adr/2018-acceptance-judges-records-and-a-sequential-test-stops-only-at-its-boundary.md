# ADR 2018: Acceptance judges records, and a sequential test stops only at its boundary

**Status**: accepted (2026-10-02)

## Context

The spec asks for three things the gate does not hold yet. A trial
count, or a sequential test valid under optional stopping, is declared
before the trials. Acceptance judges the chain of evidence against a
hidden suite, never the presence of files. Benchmarks keep scored runs
against a baseline, pinned to what produced them, with candidate and
baseline trials interleaved on one station.

Each leaves a choice open. Which sequential test, and what its bound
reports. What "the chain" is made of, and where the hidden suite's runs
live. What a benchmark's baseline is, and when a run counts as a
regression.

## Decision

**The sequential test is a likelihood ratio against a declared
alternative.** A rule declares the rate it must stay under, an
alternative rate below it, a confidence, and its most trials. Under any
true rate at or above the declared one, the ratio is a martingale of
mean one, so by Ville's inequality it ever crosses the threshold with a
chance of at most one minus the confidence, however the trials are
watched. Its bound is the lowest rate the ratio rejects, which holds
wherever the trials stop. The test stops at its first crossing, at the
first trial from which no run of passes could cross, or at its most.
The executor stops there, and the gate refuses a batch that stopped
anywhere else. A fixed count runs every trial, whatever the first ones
showed. A check with a sequential test declares no other rate.

**Acceptance reads records, never files.** The harness asks the gate
again rather than trust the verdict the loop kept. It reads the baselines,
the validations, and the hypotheses and findings from the evidence's
storage, and the work product from its system. The chain is whole when a
baseline at the scenario's base, taken before the session validated any
change, at any head, fails a visible check; every hypothesis is resolved; the gate
accepts a verified success; the result cites the validation at the head;
the hidden suite passes there; no forbidden path changed; and no surface
the agent reads names the hidden suite. The harness runs the hidden
suite itself and keeps its runs with the verdict, since the session's
evidence is a surface the agent reads. The suite lives in a source of its
own, never in the project's repository: a protected path is
write-denied, not read-denied, so a suite in the tree the workspace
checks out is one the agent can read and fit its fix to. The executor
fetches it only to run it, and a scenario that keeps it at its base is
refused. A trial's score is the share of the links held.

**A benchmark runs its own baseline, interleaved.** Each run of a
scenario holds trials of both arms, scheduled candidate, baseline,
baseline, candidate, on one station. So the baseline's score is measured
under the conditions the candidate's was, and a drift over the run falls
on both. Any lower candidate score is flagged. A benchmark is a global
row an operator records, written once, and no purge reaches it. What
it shows of a model goes to the model matrix: for each model role whose
fill the candidate changed, the model passed the scenario when the
candidate did not regress, and that result is what qualifies it there.
Only a run whose arms ran one agent kind at one version says anything of
a model; when the kind or its version changed too, the score is either's,
and the run qualifies nothing.

**The benchmark job is dispatched, never gating.** It runs `make
benchmark` over its own stack. That stack goes with the runner, so the
job exports every benchmark it recorded, each trial's verdict with the
hidden suite's runs and its cost, and the matrix's rows they fed, to a
file it uploads as the run's artifact, before the stack goes. Each
qualification an operator records cites that run's URL. The scaffold's case is a rehearsal with
scripted sessions; a product adds its scenarios, its agents on real
providers.

## Consequences

- A sequential test pays for stopping early with a looser bound: clean
  trials bound a rate under 10%, against an alternative of 2%, at the
  36th trial, where the exact bound would hold at the 29th.
- An agent kind that cannot state a hypothesis passes that link with
  none open; the link bites once the kind records them.
- A benchmark costs both arms' trials every run, and a regression is a
  flag for a person, never a block.
- The export outlives the runner, not the repository's artifact
  retention, at most 400 days: a result meant to outlast it is copied
  out of the artifact by a person.
