# ADR 2053: The gate counts a success after a baseline, and a run at the check version that governs

**Status**: accepted (2026-10-10)

## Context

A baseline comes first, so "fixed" has something to be compared with,
and a success counts only when validation passed at the version
delivered. The gate
([ADR 2009](2009-the-gate-judges-every-run-the-executor-wrote-at-the-head.md))
read the validations at the head alone, so a success with no baseline
counted. It matched a run to a requirement by the check's name, so a
run of a check whose version the policy has since changed counted too.
The baseline's rule lived in acceptance alone
([ADR 2018](2018-acceptance-judges-records-and-a-sequential-test-stops-only-at-its-boundary.md)).

## Decision

- **One baseline rule.** `rules.baseline` holds it: a baseline counts
  when it ran at the delivery's base, lists the runs it wrote, and was
  taken before the latest validation at the head. The gate and
  acceptance both call it, so a chain acceptance breaks for its baseline
  the gate refuses too, in the same words.
- **Before the validation it is compared with.** A baseline measures the
  base before the change it is compared with, and the validation at the
  head is that change's measure. So a baseline taken after the head was
  validated is not wasted: once the head is validated again, it came
  first. Counted against the first change the session validated, a
  session whose base moved, on a rebuild after its pull request merged
  or when it takes the default branch in, could never succeed again.
- **The refusal says what to do.** With no baseline at the base, the
  agent takes one, then validates the head again; with one taken after
  the head was validated, it validates the head again. The validate
  tool, the engineer's prompt, and the notice of a rebuilt branch say to
  take a baseline before validating a change, and again whenever the
  base moves.
- **The gate reads the session's validations at the base** for it, the
  oldest as many as `max_validations`, beside its read at the head.
- **A run counts at the check version the policy declares now.** A run
  at another version measured a check that no longer governs, and counts
  for nothing, passed or failed. When every run at the head of a check
  the change asks for is at another version, the gate says so, and asks
  for the head to be validated again.
- **A baseline holds across a check's new version.** It measures the
  base, which a new check version does not move. Asking for another at
  the new version would cost a session a run that shows nothing new.

## Consequences

- A session that validated its head before its baseline, or whose base
  moved, takes a baseline at its base and validates the head again
  before a success counts.
- A check whose version the policy changes is unmet until a validation
  runs it at the head, as a check the policy adds is.
- A failed run at a check's old version no longer holds back a pass at
  its new one.
