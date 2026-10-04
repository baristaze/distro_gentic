# ADR 2032: A product's automation action checks its writer when the automation is written

**Status**: accepted (2026-10-04)

## Context

A product adds its own kind of automation action (ADR 2031). When an
automation of that kind is written, the platform holds its params to the
kind's shape, and nothing more. No hook sees who writes it. A product
whose action only named approvers may start refuses the others only in
the firing, under the run's context. So a member outside the approvers
writes an automation that is saved, and refused at every firing after,
and so does an approver who sets it to run as the tenant's principal.
They learn it from a string of refused runs, not when they could fix
it.

## Decision

**A product's kind checks its writer.** `AutomationActionInterface`
gains `check_writer(ctx, params, runs_as)`. The create and the edit of
an automation of that kind call it after the params hold to the kind's
shape, under the writer's own context, in person, with whom the
automation runs as. A refusal answers as the kind raised it:
`NotAuthorized` is a 403 with the kind's reason. Every kind declares
it, as an interface's every operation is declared. A kind with no rule
of its own returns, and admits every writer the platform admits.

**It tells the writer, and sees whom the automation runs as.** The
writer is the person who sets the work going, and the one who can fix a
refusal, so the check runs under their context. An edit makes its editor
the creator, so the person checked is the person the automation runs
as, or the creator the principal's grant is held to. One set to run as
the principal fires under the principal's context, so the kind is told
`runs_as`, and refuses that automation when its `act` would refuse the
principal.

**A disabled automation is never asked about.** Nothing deletes an
automation, so turning one off is how its writer stops it. A writer the
kind no longer admits can still do that. Turning it on again is an edit,
and the kind checks that editor.

**The firing still refuses what changed.** A writer's standing can
change after the write. The kind's `act` still runs under the run's
live context, and its refusal still refuses the run.

## Consequences

- A product's kind adds `check_writer` when its product takes this
  release. One that returns keeps every writer it had.
- The check runs once a write, under the writer's context. It reads
  only what that person may read.
- An automation stored before its kind added a rule keeps firing until
  it is edited, and its firings refuse what the kind refuses.
- The platform's own two actions are never a product's to check.
