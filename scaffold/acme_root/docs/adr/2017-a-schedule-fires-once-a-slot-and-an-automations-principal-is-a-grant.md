# ADR 2017: A schedule fires once a slot, and an automation's principal is a grant

**Status**: accepted (2026-10-02)

## Context

Automations: "A trigger, an event with filters or a schedule, leads to an
action ... An automation runs as its creator or as the tenant's
automation principal." The guideline keeps time without a scheduler:
every worker sweeps on its own timer, idempotent and serialized by the
database ([Maintenance Without a Scheduler][g-sweep]). So every worker
ticks every tenant, and a schedule must not fire once per worker.

A session's project keys its budget and its policies
([ADR 2016](2016-a-sessions-project-is-set-before-it-and-never-moves.md)),
and a session started in none takes its tenant's alone.

The engine names a steady principal "its creator, or a service principal
the tenant grants", and asks the adopter's transition for a principal's
live context at every call. The tenancy manager answers for a member and
grants no service principal.

## Decision

**A schedule fires for a slot.** Its slots are its creation time and
every period after it. A tick fires the slot it is in, under a run id
derived from the automation and the slot, so the ticks of several
workers in one slot meet one run, and the admission's lock on the
automation's row serializes them. A slot that passed while no tick came
is not fired late: a schedule fires at most once a period, never in a
burst after an outage.

**The automation principal is a grant.** A tenant holds one, with one
role, granted in person by a person who manages its members, never above
their own role and never the service role. A second grant changes the
role and keeps the principal's id. Its live context is answered by its
own transition, `automation_principals`, from the grant read at each
call: the granted role's permissions and nothing else, whichever kind a
step names it as. Every other principal falls through to the members'
transition. A root that runs the sessions an automation starts hands the
same transition to the managers, so their calls are answered by the grant.
An automation that runs as the principal is made only once the principal
is granted, and only by a person whose own role is at least the grant.
Each firing reads the grant and its creator's role then, and is refused,
starting no session, when the grant is above that role or the creator
left: nobody lends themselves a role through the principal. The check is
at the firing, since the transition answers each call by the grant alone
and knows no creator. A session already running when the grant is
raised, or its creator moved below it, makes its remaining calls at the
grant.

**An automation's session starts in a project.** Its start names a
project of the tenant, read when the automation is saved: another
tenant's is refused there, as one that never existed is. The firing
starts the session through the projects' start, so it is in its project
from its first moment, and the project's budget and policies hold every
call it makes. Outside a local stack, a start that names no project is
refused when it is saved, and one stored with none is refused at each
firing, before its limits reserve anything: its run records why, and no
session starts.

**An automation's station job holds its pool's line.** Its pool is one
of the tenant's, read when the automation is saved: another tenant's is
refused there, as one that never existed is. The firing joins the pool's
line as the automation runs, carrying the job, and the run holds the
place as a session would, at work until the job's run is recorded. The
job calls no model, so the run's share of the cost cap goes back once it
joins; the rate and the concurrency hold it.

## Consequences

- An automation run as the principal starts nothing its role cannot
  start, though its creator could; the run is refused, with no session.
- Changing the grant's role changes what every such session's next call
  may do. A grant raised above an automation's creator stops its next
  firing, not a session it already started.
- Before a principal is granted, no automation that runs as it is made.
- An automation stored with no project fires only refused runs outside
  `local`. One that names a project is made in its place.
- A station job's run counts in the concurrency while it waits in line,
  so a busy pool queues or refuses the automation's next firings.
- The transition is a second site that builds a tenant context beside the
  tenancy manager's, and the stage checks list it.
- A schedule's period is its own, not the sweep's: a sweep interval longer
  than a period fires the schedule at the sweep's pace.

[g-sweep]: https://github.com/baristaze/swe_guidelines/blob/v0.48.0/architecture.md#maintenance-without-a-scheduler
