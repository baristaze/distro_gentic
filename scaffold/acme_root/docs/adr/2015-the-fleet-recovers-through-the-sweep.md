# ADR 2015: The fleet recovers through the sweep

**Status**: accepted (2026-10-03)

## Context

The platform's spec, Failure at Fleet Scale: when a provider fails,
every session that meets its outage signal parks, naming the provider,
and when the signal's retry time passes the parked sessions are woken,
staggered. Sessions die with their runners, and the platform notices
through the guideline's sweep, which every cloud worker runs and no host
or daemon does. The platform adds its duties to that sweep: among them,
a hold nobody settled settles at usage retrieved from the provider, else
at its full amount, and is released only when the provider provably did
not bill; and a session with a pending input and no queued loop is
woken.

The engine already settles a lost call's hold when the session's next
run finds the call open. A hold whose run died before its request was
written, or whose session never runs again, is found by nothing. It
reserves its lines until it settles, and its spend counts nowhere.

## Decision

**An outage's wakes spread after its retry time.** A park on a provider
asks to be woken at its retry time plus a share of a spread, a minute by
default. The share is drawn from the session and the retry time, so the
sessions one outage parked wake in turn and never before the retry
time. Other parks wake at their time: a tenant's own, such as a
budget's, are bounded by its fair share.

**A hold an hour open settles through its gate.** The maintenance
worker's pass reads, across tenants, the holds opened an hour ago or
more that no settlement closed, and settles each through the gate that
holds it: at the bill the provider gives, else whole. Nothing but the
provider's proof releases one. No provider answers for one call after
the fact today, so the bill is unknown, and the hold counts whole: the
worst case it reserved, never below what was billed. A run that holds
its lease stops within half of it once the lease is lost, so an hour
outlasts every call a live run can still settle. Each worker reads on
from where its last pass stopped, one slice of opening times per read,
and its first pass reads a day back. An index on the holds' opening
time bounds each read.

**A session pending past a run's time asks for its run again, once a
write.** The pass reads, across tenants, the sessions pending with no
write for twenty minutes, longer than a run may take before it hands
its loop back. It asks for each one's run as the person who made the
session, as a wake does, under a key drawn from the session's version.
A pass that finds it again asks nothing more. The run that takes it up
asks an approval that expired meanwhile again, at its gate.

## Consequences

- A call still streaming an hour after its hold finds the hold settled
  whole. Its own settlement answers that first one, so a spend past the
  worst case is lost to the count. The engine's worst case already
  bounds a call's spend.
- A session whose loop waits in its lane longer than twenty minutes, in
  a backlog or while its runners are down, gets one more loop item. The
  fair-share guard defers it as it does the first, and a run that finds
  nothing to do writes nothing.
- A session whose asked-for run fails for good stays pending until a
  write moves it or an operator requeues the dead letter, as any dead
  letter does.
- The duties of the relay, the stations, and their lines join the same
  list when those parts land: each one's own, across tenants, bounded,
  and safe to run twice.
- The sweep reads the ledger the gate writes. A root that wires another
  gate wires the read of its ledger with it.
