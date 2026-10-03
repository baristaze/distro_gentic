# ADR 2002: A tenant's loops are held at the claim, in the claim order

**Status**: accepted (2026-10-02)

## Context

A session makes several kinds of work, and each must run where its
environment is: a loop on the platform's runners, and a command on the
host that holds its workspace. The guideline's work queue already has
lanes, and a lane for a tenant whose bulk work starves its neighbours.
Loops are long and they are the cost, so each tenant also has a limit
on how many run at once.

The engine enqueues every item on the lane its producer names, and a
relayed item on the default lane. Its claim takes the oldest item of a
lane, and a handler's guard hands an item back with no attempt spent.

A limit checked when a loop is enqueued holds nothing: the loop waits in
the queue and runs later, past the limit. A limit checked by counting a
tenant's running loops after a claim has two failures. Two loops claimed
together each count the other, both go back, and both come back
together, forever. And a slot reserved apart from the queue row must be
freed by every way a run ends, a lost runner's included.

## Decision

**The lane is placement's answer, at every enqueue.** The work manager
asks placement for the lane of each item it enqueues, direct or
relayed. A loop goes to its tenant's lane: its plan tier's, or one of
its own when an operator gave it one. A kind a host runs goes to the
lane its payload names. No producer picks a lane.

**A host is claimed for by its identity.** The control
plane claims on its behalf, from the lanes and kinds its identity
names, and never from what its call asks for.

**The guard counts the loops ahead in the claim order.** A claimed loop
runs while fewer of its tenant's loops are claimed under a live lease
ahead of it than its share allows: before it in the claim order on its
lane, and every one on another lane, where the order says nothing.
Otherwise it goes back to its lane for a delay, through the engine's
guard, with no attempt spent. The queue row is the record; nothing else
is reserved.

## Consequences

- Of two loops claimed together, the later in the claim order waits and
  the earlier runs, so neither waits on the other forever.
- A runner that lost its lease no longer counts once its lease has run
  out, so a tenant at its limit recovers its loop at the next claim.
- Two claims of one lane that commit together can each miss the other,
  for the moment a claim takes, and a tenant can then run one loop past
  its share until either loop ends. Holding that moment would take a
  lock on every claim, and the excess is bounded and short.
- A loop over its share is claimed again after each delay, so a full
  tenant's queue costs a claim, a count, and a hand-back per loop per
  delay.
- Each lane in use needs runners of its own. An operator who gives a
  tenant a tier or a lane no runner serves leaves its loops waiting,
  which the queue's age alarm reads.
- The engine's work manager gains the lane hook and the count of the
  claims ahead, so the next move of the base merges over both.
