# ADR 2031: A product adds its own kind of automation action

**Status**: accepted (2026-10-03)

## Context

Automations: "A trigger, an event with filters or a schedule, leads to an
action: start a session, or message a standing session." Those were the
only two, a closed enum. A product whose firing does its own work, a job
that waits in a line of its own and ends without a session, had no
hook. It edited the platform's automations, which every base move then
fights, or it started a session only to run one job.

A run that names no session is closed once `lost_after` passes, since
the platform reads it as a run lost before its action ran. A product's
job can run far longer than that, and its run would close while the job
still holds its machine, so the concurrency would let the next firing
start beside it.

## Decision

**A product declares its kinds of action in `PRODUCT_KINDS`.** Each is
an `AutomationActionInterface` (`automations/actions.py`): a name, the
shape its params hold to, a handler, and a check. `ProductKinds.actions`
builds them over the managers, as a product's tools are built, and
`build_automations` registers them in every process that writes or
fires an automation.

**Its handler acts in the firing.** It runs as the automation runs, as
its creator or its principal, after the limits started the run. It
answers the id of the work it started, derived from the run's, so a run
acted on again lands its work once. The run keeps that id, and a
handler's `PlatformException` refuses the run, as an engine's refusal of
a session does.

**Its check says when the run ended.** A run that names a product's work
stays at work, and counts in the concurrency, until the check answers
succeeded or failed. The run closes with that outcome. A check that
raises leaves the run open, since its work may still be running, and the
next firing asks again. `lost_after` holds only a run that names no
session and no work.

**Its name is never the platform's.** A kind named as one of the
platform's actions, or twice, is refused at boot. An automation whose
action names a kind no product declares, or params off its kind's shape,
is `ValidationFailed` when it is written. One whose kind left the
product since it was written is refused at each firing, with the
refusal `action`.

## Consequences

- The action's kind is a name, not an enum. A session's action carries
  the creator's brief and no params, and a product's carries its params
  and no brief, project, or session.
- The run gains `work_id` and `outcome`, both nullable, in one
  migration. Its down migration removes the automations of a product's
  kind, with their runs, since the previous release reads them as
  malformed.
- The portal's form edits the platform's two actions. It shows a
  product's by its kind and offers no form for it: the product writes
  its own.
- A product's run reserves its share of the cost cap as a session's run
  does, and holds it while it is at work. No budget is put on the
  product's work: it starts no session, so no model call of the
  platform's draws on it.
