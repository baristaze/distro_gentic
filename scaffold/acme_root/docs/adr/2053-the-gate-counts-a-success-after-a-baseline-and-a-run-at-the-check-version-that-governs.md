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
  when it ran at the base, lists the runs it wrote, and was taken before
  the session validated any change from that base. The gate and
  acceptance both call it, so a chain acceptance breaks for its baseline
  the gate refuses too, in the same words.
- **From that base.** The base is where the branch meets the default
  branch, and it moves when the branch takes the default in. Counted
  against every change the session ever validated, a session whose base
  moved could never succeed again. A baseline at the new base, taken
  before a change from it is validated, counts.
- **The gate reads the session's oldest validations** for it, as many
  as `max_validations`. A baseline comes first, so the one that counts
  is among them; one taken past them counts for nothing. Its read at the
  head is unchanged.
- **A run counts at the check version the policy declares now.** A run
  at another version measured a check that no longer governs, and counts
  for nothing, passed or failed. When every run at the head of a check
  the change asks for is at another version, the gate says so, and asks
  for the head to be validated again.
- **A baseline holds across a check's new version.** It is taken once,
  before the change. Asking for another at the new version would leave a
  session no way to succeed once its policy moved.

## Consequences

- A session that validated a change before its baseline ends failed or
  inconclusive, never succeeded.
- A check whose version the policy changes is unmet until a validation
  runs it at the head, as a check the policy adds is.
- A failed run at a check's old version no longer holds back a pass at
  its new one.
