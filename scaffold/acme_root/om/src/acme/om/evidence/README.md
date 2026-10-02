# Evidence

What makes a result. The work an agent delivers is not the result: the
result is the evidence that the work does what was asked, at the version
delivered. This is one of the kinds of thing [Acme is made
of](../../../../README.md).

## What it holds

- **Run**: one execution of one check. It records the version it ran
  against and whether the tree held uncommitted changes, the environment
  (an image and a toolchain), the host and its isolation, who ran it and
  wrote its results, the check and its version, its parameters, metrics,
  timing, and outcome, and its artifacts, each with a hash. A run is
  written once and never changed.
- **Provenance**: what served a run. Each thing a run relied on is
  `real`, a `twin`, a `double` (a test double), or `unavailable`. A run
  reports its weakest: one twin makes it a twin's run.
- **Hypothesis** and **finding**: what may explain a behavior, and what
  the runs show. Each links the runs that support or refute it. What one
  says stays in the agent's step that stated it.
- **Validation policy**: a project's say over what counts. It declares
  the project's checks, which ones a change must pass and at what grade,
  for which paths, and the paths an agent may not change: the checks,
  their fixtures, and whatever changes how tests are found or how the
  runtime starts.
- **Validation**: one pass of the policy's checks on a fresh executor,
  from the delivered commit, with the checks, fixtures, and runner taken
  from the version the work started from. A **baseline** is the same pass
  at that starting version, before any change.
- **Rate claim**: what repeated trials show of a failure rate: never the
  rate, only a bound under it at a declared confidence.

## What can happen

- **Declare** a policy. A person who manages the tenant writes it; an
  agent never does.
- **Record** a run of the agent's own, or a hypothesis or a finding.
- **Validate** the session's work, or take its **baseline**. The executor
  runs the checks, writes and hashes the results, and every run it wrote
  is kept with the validation, or none is.
- **Submit** a result. The gate judges it.

## The rules

- **A double is never validation, and a twin is never real.** A check
  passes at its grade only on runs the real thing, or a twin where the
  policy accepts one, served.
- **The agent cannot change a protected path.** A tool that would change
  one is denied whatever any policy layer allows, and a change that
  touches one voids validation.
- **Validation runs apart from the agent.** Never in its workspace, never
  with checks from the delivered tree, never under an environment it set.
- **One gate decides.** A success that changed the work product counts
  only when the policy passed at the committed head, on a clean tree, on
  runs the validation's executor wrote, with every run of every check at
  that head counted. A failure explained by runs is a result. A success
  that validated nothing is inconclusive.
- **A rate is bounded, never zero.** An exact or Wilson bound at a
  declared confidence, after the trial count the policy declared; a trial
  a safety stop ended is classified by the declared rule, never dropped;
  rates judged together correct their confidence.
- **The hidden suite stays hidden.** A scan of every surface the agent
  reads finds any mention of it.
- **Every run belongs to one org,** and goes with its session or with its
  tenant.

## How another namespace composes it

The agents' loop passes a submitted result through the gate this
namespace supplies. A tool that changes files asks it whether a path is
protected, and reports the answer as its target. The work product a
session delivered, and the executor validation runs on, are the
platform's ports (`work_product.py`, `executor.py`), which a root wires.
