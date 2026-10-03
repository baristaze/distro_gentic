# Evidence

Group id: `evidence`. Covers Evidence of `distro_gentic_spec.md`, and the
promises What Closes a Loop makes that evidence keeps.

This group judges what makes a result: the execution record and its
provenance, hypotheses and findings, the validation policy and its
protected checks, the baseline, statistical evidence, the result gate,
the results contract, and acceptance and benchmarks. It leaves feedback
that returns after delivery and the twin each integration has to
`intake`, a validation session's place on the queue to `fleet`, and the
engine's done rules to the engine.

## EVD-01 The platform enforces the loop's promises

**Principle.** A platform claims a closed loop only if it keeps seven
promises: every execution is recorded, a baseline comes first, work
completes through one gate, failed and inconclusive are first-class,
feedback returns, success is judged by behavior, and autonomy stops
exactly where policy says. A platform enforces each of them; it never
just hopes for it.

**Source.** What Closes a Loop.

**Look for.** For each promise, the mechanism that holds it: a record, a
gate, a refusal, a check.

**Violation.** A promise held only by an instruction in a prompt, a
playbook, or a skill the agent may skip; a promise with no mechanism
that refuses its breach.

**Severity.** high

**Check.** review

## EVD-02 Every execution is a record of its version and environment

**Principle.** Every execution is recorded, durably, tied to the version
and the environment it ran in. Its record holds the version it ran
against, whether the tree had uncommitted changes, the environment (an
image digest, the toolchain), the host and isolation it ran under, the
check and its version, its parameters, metrics, timing, outcome, and its
artifacts, each with a hash and a provenance.

**Source.** Evidence, Execution Records; What Closes a Loop.

**Look for.** The execution record's fields; every path that runs a
check or a command, and whether it writes one.

**Violation.** An execution with no record, or a record without its
version, whether the tree was clean, its environment, its host and
isolation, or its check's version; an artifact with no hash or no
provenance.

**Severity.** high

**Check.** review

## EVD-03 Every dependency has a provenance, and a double never validates

**Principle.** Every dependency an execution relied on carries a
provenance: `real`, `twin`, `double` (a test double), or `unavailable`.
A double is never validation, and twin evidence is never reported as
real.

**Source.** Evidence, Execution Records.

**Look for.** Where an execution records the provenance of each
dependency; what the gate and the report do with a `double` or a
`twin`.

**Violation.** A dependency with no provenance, or one recorded `real`
when a twin or a double served it; a double's run counted as
validation; twin evidence in a report with no mark that a twin served
it.

**Severity.** high

**Check.** review

## EVD-04 Hypotheses and findings are records, and the plan a projection

**Principle.** Hypotheses and findings are records too, each linked to
the runs that support or refute it. The plan is a projection of the
agent's steps, never chat.

**Source.** Evidence, Execution Records; What Closes a Loop.

**Look for.** How a hypothesis or a finding is stored, and what it links
to; where the plan a viewer sees comes from.

**Violation.** A hypothesis or a finding kept only in the agent's text,
or with no link to a run; a plan stored as a message or a document
beside the steps.

**Severity.** high

**Check.** review

## EVD-05 Validation is declared, and its checks are protected

**Principle.** Each project declares a validation policy: which checks
must pass, at what grade, for which kinds of change, for a success to
count. The checks, their fixtures, the policy itself, and every path
that changes how tests are found or how the runtime starts are
protected, by pattern: the agent cannot edit them, and a change that
touches one voids validation.

**Source.** Evidence, Validation Policy and Protected Checks.

**Look for.** The validation policy's declaration; the protected
patterns and what they cover; what a change that touches a protected
path does to validation.

**Violation.** A success counted with no declared policy; a check, a
fixture, the policy, or a path that finds tests or starts the runtime
that no protected pattern covers; an agent's edit to a protected path
accepted, or a change that touches one and still validates.

**Severity.** high

**Check.** review

## EVD-06 Validation runs apart from the agent

**Principle.** Validation never runs in the agent's workspace. It runs
on a fresh executor, from the delivered commit, with the checks,
fixtures, and runner taken from the protected source, under an
environment the agent did not set. The executor writes and hashes the
results, and the gate accepts only results whose provenance names it.

**Source.** Evidence, Validation Policy and Protected Checks.

**Look for.** Where validation runs, and from which commit; where its
checks, fixtures, runner, and environment come from; who writes and
hashes the results, and what the gate checks of them.

**Violation.** Validation run in the agent's workspace or on a reused
executor; checks or fixtures taken from the delivered tree instead of
the protected source; an environment the agent set; results the agent's
tools wrote, or a gate that accepts results whose provenance does not
name the executor.

**Severity.** high

**Check.** review

## EVD-07 A baseline comes first, and a check nobody ran is a claim

**Principle.** A baseline comes first, recorded before a change, so
"fixed" has something to be compared with. It runs the same checks at
the base version before any change, and for an intermittent defect it
reproduces the defect at a measured rate. A check nobody ran is a claim,
not evidence.

**Source.** Evidence, Validation Policy and Protected Checks; What Closes
a Loop.

**Look for.** When the baseline runs, at which version, and with which
checks; how an intermittent defect's rate is measured; how a report
cites the checks it rests on.

**Violation.** A change made before its baseline is recorded; a baseline
at another version or with other checks; an intermittent defect with no
measured rate; a report that cites a check no execution record shows
was run.

**Severity.** high

**Check.** review

## EVD-08 A rate is bounded, never shown to be zero

**Principle.** Intermittent behavior needs repeated trials, and a rate is
never shown to be zero, only bounded. A claim about a rate reports a
one-sided exact or Wilson bound at a declared confidence, never a normal
approximation, which collapses at zero failures. The trial count, or a
sequential test valid under optional stopping, is declared before the
trials.

**Source.** Evidence, Statistical Evidence.

**Look for.** How a rate claim is computed and reported; where the
confidence, and the trial count or the sequential test, are declared,
and when.

**Violation.** A rate reported as zero, or bounded by a normal
approximation; a bound with no declared confidence; a trial count chosen
after the trials, or trials stopped early under a test not valid under
optional stopping.

**Severity.** high

**Check.** review

## EVD-09 Every trial counts, and candidate and baseline interleave

**Principle.** The gate counts every trial at that version, and an
aborted trial is classified by a declared rule, never dropped. Candidate
and baseline trials interleave on the same host, and a claim across
many scenarios corrects for the number of comparisons.

**Source.** Evidence, Statistical Evidence.

**Look for.** Which trials the gate counts; how an aborted trial is
classified; how candidate and baseline trials are scheduled; how a claim
across scenarios is corrected.

**Violation.** A trial at the version dropped from the count; an aborted
trial dropped, or classified by no declared rule; candidate and baseline
run in separate blocks or on different hosts; a claim across
scenarios with no correction for the number of comparisons.

**Severity.** high

**Check.** review

## EVD-10 Work completes through one gate

**Principle.** Work completes through one gated tool. It records the
outcome (succeeded, failed, or inconclusive), the report, the
uncertainties, and the runs each claim cites. It refuses a success that
changed the work product unless the validation policy passed at the
committed head, with a clean tree, on results its executor wrote. A run
that validated nothing gets no exemption; it is inconclusive. A failure
with an evidence-backed explanation is a result.

**Source.** Evidence, The Result Gate; What Closes a Loop.

**Look for.** Every path that completes work; the gate's checks on a
success; what it records.

**Violation.** A path that completes work without the gate; a success
accepted at a head other than the validated one, with a dirty tree, or
on results the executor did not write; a run that validated nothing
recorded as succeeded; a claim that cites no run.

**Severity.** high

**Check.** review

## EVD-11 The platform defines the results protocol, never the runner

**Principle.** The platform defines the protocol, never the runner. A
check is declared: a command template, its kind, the capabilities it
needs, and the version of the results schema it writes. A run writes a
strict, versioned results file and streams its cases as they finish. A
compatibility check refuses a run before anything runs. One collector
serves every place a check can run.

**Source.** Evidence, The Results Contract.

**Look for.** The check declaration; the results file's schema and its
version; where compatibility is checked; the collectors.

**Violation.** A test runner the platform requires; a check with no
declared template, kind, capabilities, or schema version; a lenient or
unversioned results file; an incompatible run found only after it
started; a second collector for a place a check runs.

**Severity.** medium

**Check.** review

## EVD-12 Acceptance hides its suite and judges the chain of evidence

**Principle.** Acceptance judges an agent's work the same way. The
objective hides its root cause. A hidden suite must pass beside the
visible one, and the result is judged by behavior, so any valid fix
passes. Editing the checks or the system under test is forbidden and
checked. No surface the agent reads mentions the hidden suite, and a
scanner checks every one. The harness judges the chain of evidence (a
failing baseline, the runs, the hypotheses resolved, a clean validation,
a cited report), never the presence of files.

**Source.** Evidence, Acceptance and Benchmarks; What Closes a Loop.

**Look for.** How acceptance runs the hidden suite; the scanner and the
surfaces it covers; what the harness scores.

**Violation.** An acceptance verdict without the hidden suite; a prompt,
knowledge, a tool source, evidence, or a pull request that names the
hidden suite, or a surface the scanner skips; a harness that scores the
presence of files; an edit to the checks or the system under test that
goes uncaught.

**Severity.** high

**Check.** review

## EVD-13 A benchmark is pinned to what produced it

**Principle.** Benchmarks follow from acceptance: preserved runs, judged
scores, their cost, and regressions flagged against a baseline, each
pinned to the fill set and agent-kind version that produced it.

**Source.** Evidence, Acceptance and Benchmarks.

**Look for.** A benchmark result's record: its runs, its score, its
cost, its baseline, its fill set, and its agent-kind version.

**Violation.** A benchmark score with no preserved runs or no cost, or
not pinned to its fill set and agent-kind version; a regression not
flagged against a baseline.

**Severity.** medium

**Check.** review
