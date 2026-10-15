# ADR 2002: A loop goes to its tenant's lane, and a host is claimed for by its identity

**Status**: accepted (2026-10-02)

## Context

A session makes several kinds of work, each running where its
environment is: a loop on a runner, a command on the host that holds its
workspace. The guideline's work queue has lanes, among them one for a
tenant whose bulk work starves its neighbours. Loops are long and are
the cost, so a tenant also has a limit on how many run at once.

The engine enqueues an item on the lane its producer names, a relayed
item on the default lane, and its claim takes the oldest item of a lane.
A producer that picks its own lane can put a tenant's loops where its
plan tier does not, and a host that names its own lanes can claim work
its identity never held.

## Decision

**The lane is placement's answer, at every enqueue.** The work manager
asks placement for the lane of each item it enqueues, direct or relayed.
A loop goes to its tenant's lane: its plan tier's, or one of its own
when an operator gave it one. A kind a host runs goes to the lane its
payload names. No producer picks a lane.

**A host is claimed for by its identity.** The control plane claims on
its behalf, from the lanes and kinds its identity names, never from what
its call asks for.

**The count of the loops ahead says why a loop waits.** For a standing,
placement counts a tenant's loops claimed under a live lease ahead of an
item: those before it in the claim order on its lane, and every one on
another lane, where the order says nothing. How many of a tenant's loops
run at once is the work queue's cap on the lane, never a guard of the
platform's own
([ADR 2048](2048-a-tenants-share-of-the-loops-is-the-work-queues-cap.md)).

## Consequences

- Each lane in use needs runners of its own. An operator who gives a
  tenant a tier or a lane no runner serves leaves its loops waiting,
  which the queue's age alarm reads.
- The engine's work manager carries the lane hook and the count of the
  claims ahead, so each move of the base merges over both
  ([ADR 2064](2064-the-platform-wires-in-files-of-its-own-and-a-product-declares-its-namespaces.md)).
