# ADR 2048: A tenant's share of the loops is the work queue's cap

**Status**: accepted (2026-10-09)

## Context

Loops are long and are the cost, so a tenant's share of them is held at
the claim. The guideline's work queue holds a cap there: a lane's cap on
the items one tenant holds claimed
([ADR 0087](0087-a-tenants-share-of-a-lane-is-held-at-the-claim.md)),
and a tenant's own cap on a lane in its place, which an operator sets
([ADR 0093](0093-a-tenants-own-cap-holds-in-place-of-the-lanes.md)).
The claim passes over a tenant at its cap in its one statement, so the
tenant's item is not written and spends no attempt.

A guard of the platform's own beside it
([ADR 2002](2002-a-tenants-loops-are-held-at-the-claim-in-the-claim-order.md))
is a second cap, which can disagree with the first. It also costs more:
a loop over its share is claimed, handed back, and claimed again after a
delay, a write each time, while a freed runner idles until the delay
passes.

The plan tiers stay the platform's own: each tier's lane, and how many
loops one tenant holds there. So does an operator's move of a tenant to
a lane of its own, and the share route an operator writes.

## Decision

- **Each tier's share is its lane's cap.** `PlacementOptions.tier_shares`
  names a tier's share, and `default_share`, eight, holds for a tier it
  does not name and on a tenant's own lane. A runner passes its lane's
  cap to the claim (`PlacementManagerInterface.lane_cap`), as the
  maintenance worker passes its own.
- **A tenant's own cap is the work queue's.** The share route,
  `PUT /admin/orgs/{org_id}/share`, writes the tenant's plan tier and its
  own-lane move to its share, and its `concurrency` as the tenant's own
  cap on its loop lane, through the work queue's operator plane, which
  leaves the cap's trail. Without `concurrency`, the route clears that
  cap, so the tier's share holds. A move to another lane takes the cap
  off the lane the tenant leaves. The cap lands before the share, so a
  failure between leaves a cap on a lane the tenant's loops do not reach
  yet, which the operator's retry writes again.
- **The platform holds no guard of its own.** The runner's guard and its
  delay go, in place of ADR 2002's guard; its lanes, placed at every
  enqueue, stay. Its count of a tenant's loops ahead of an item stays, for
  the standings, which say why a loop waits.
- **A share the release before wrote is carried once.** Its concurrency
  lives in `core` and the caps in `queue`, and nothing crosses a role, so
  no migration can carry it. The release before still reads the column,
  so it stays, with a default for a share this release writes, beside a
  marker, `cap_carried`, false on every share there is. The maintenance
  sweep writes each unmarked share's concurrency as the tenant's own cap
  on its loop lane, unless the tenant holds one there already, then
  marks the share. A write of the share marks it too, since the write is
  newer. A later release drops the column, the marker, and the step,
  once no release before reads them.

## Consequences

- One cap holds a tenant's loops on a lane: its tier's or its own, never
  a second number beside it.
- A loop of a tenant at its cap waits where it is, so a freed runner
  takes it at the next claim, and a full tenant's queue costs no claim
  and no write.
- Until the sweep's first pass after the deploy, a share the release
  before wrote is held to its tier's share, not to its own number.
- A share the release before writes while both releases run is carried
  when it is new. A change it makes to a share already carried is not.
- A tenant on its own lane whose own cap is cleared is held to the
  default share.
- Two claims that commit together can each miss the other, as the
  guideline's cap allows, so a tenant can run past its cap by the claims
  of that moment.
