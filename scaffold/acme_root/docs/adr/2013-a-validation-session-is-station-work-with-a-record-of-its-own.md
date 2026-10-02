# ADR 2013: A validation session is station work with a record of its own

**Status**: accepted (2026-10-02)

## Context

A platform ships a few agents, each a profile over the engine's one
loop. It also runs checks with no agent at all: a validation session
runs a check on a station, on the same queue and the same record as an
agent's work.

The engine's agent session is the obvious record to reuse. But its loop
is the engine's: a message to it asks for a loop, a runner claims the
loop, and the loop's first act after its gates is a model call. A kind
must name a main model role. An agent session with no agent would be one
whose loop must never run, held only by every path that could wake it.
Its history is the model's too: its tool steps reference the model
response that asked for them.

## Decision

**A validation session is a record of its own.** It holds the check,
its version, its parameters, and the lab whose station runs it, and,
once the run is recorded, the id of that run's execution record.

**Its work is station work on the queue.** Starting one writes the
session and asks for one `station` item in the same commit, through the
outbox, as every write that starts work does. Placement puts the item on
the lab's lane, and the lab's daemon claims it through the gateway, as
it claims any station work.

**Its run is the execution record every run is.** The daemon's report
writes the record through the evidence namespace, and finishing the
session names it. A session runs its check once.

## Consequences

- No path of a validation session asks for a loop, so no runner claims
  it and no model is called: there is nothing to hold shut.
- It is listed, retained, and purged on its own, not with agent
  sessions; a tenant past its retention loses it with the sweep.
- Nothing finishes a session until a daemon's report does: the station
  daemon and its report through the gateway come with stations.
