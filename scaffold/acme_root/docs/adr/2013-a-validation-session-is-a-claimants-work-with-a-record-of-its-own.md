# ADR 2013: A validation session is a claimant's work with a record of its own

**Status**: superseded by [ADR 2024](2024-a-validation-session-is-platform-work-on-the-fresh-executor.md) (2026-10-03)

## Context

A platform ships a few agents, each a profile over the engine's one
loop. It also runs checks with no agent at all: a validation session
runs a check through a claimant outside the platform, on the same queue
and the same record as an agent's work.

The engine's agent session is the obvious record to reuse, but its loop
is the engine's: a message to it asks for a loop, a runner claims the
loop, and the loop's first act after its gates is a model call. A kind
must name a main model role, so an agent session with no agent would be
one whose loop must never run, held shut only by every path that could
wake it. Its history is the model's too: its tool steps reference the
model response that asked for them.

## Decision

**A validation session is a record of its own.** It holds the check,
its version, its parameters, and the group whose claimant runs it, and,
once the run is recorded, the id of that run's execution record.

**Its work is a claimant's work on the queue.** Starting one writes the
session and asks for one item of the claimant's kind in the same commit,
through the outbox, as every write that starts work does. Placement puts
the item on the group's lane, and the group's claimant claims it through
the gateway, as it claims any of its work.

**Its run is the execution record every run is.** The claimant's report
writes the record through the evidence namespace, and finishing the
session names it. A session runs its check once.

## Consequences

- No path of a validation session asks for a loop, so no runner claims
  it and no model is called: there is nothing to hold shut.
- It is listed, retained, and purged on its own, not with agent
  sessions; a tenant past its retention loses it with the sweep.
- Nothing finishes a session until the claimant's report does: the
  claimant and its report through the gateway come with the domain that
  runs the check.
