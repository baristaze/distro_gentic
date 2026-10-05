# ADR 2036: A message to a standing session waits for a budget that ends with its run

**Status**: accepted (2026-10-04)

## Context

The platform's spec, Automations: an automation has limits of its own,
and each run it starts is held to `run_cap_micros` of its cost cap
([ADR 2017](2017-a-schedule-fires-once-a-slot-and-an-automations-principal-is-a-grant.md)).
A start holds its run with a `LIFE` budget on the new session's tree,
made before the brief wakes it. That tree is the run's alone, so the
budget binds nothing else.

A message wakes a standing session, whose tree outlives the run. The
engine's budgets have no end: a budget is created, its amount changes,
and it goes only with its tenant. A budget made for one run on the
standing session's tree would count every later loop's spend too, and
park the session once that spend passed the run's cap. One made for
each run would pile up until the money gate refuses every call past its
bound on the budgets one call reads. With no budget, the woken session
spends under no cap of the run's at all.

## Decision

**A message to a standing session is refused while it is enabled.**
Written enabled, the automation is `ValidationFailed`, with the reason.
Stored enabled, each firing is a run refused for its action: it reserves
nothing and sends nothing. A disabled one saves, so its writer can
always turn it off.

**It acts once the engine's budget can end with a run.** That takes a
budget that ends: one closed with its run, or one with an end time.
Then a message's run takes such a budget on the standing session's
tree, made before the brief and ended with the run, as a start's is.

## Consequences

- A standing session, such as a CI triage one, is woken by a person or
  by a product's own action meanwhile.
- The portal still offers the action, and saving it answers with the
  reason.
- A start's run is held as before, and its budget stays the tree's.
