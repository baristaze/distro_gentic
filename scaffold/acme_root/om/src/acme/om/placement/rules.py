"""Pure rules of the placement namespace: the lanes work goes to, the cap
each loop lane passes to the claim, and the bounded labels of the
platform's gauges. Values in, values out; no clock, no storage, no settings. The lane of each kind, and
the lanes and kinds a claimant's identity claims, are the kinds' registry's
(`placement.kinds`)."""

from collections.abc import Mapping
from datetime import timedelta
from uuid import UUID

from acme.om.placement.types.share import FairShare
from acme.om.work.types.work_item import WorkKind, relayed_lane

DEFAULT_TIER = "standard"
"""The plan tier of a tenant no operator has given one."""

LOOP_LANE_PREFIX = f"{relayed_lane(WorkKind.LOOP)}:"
"""The stem of every loop lane: the loop's own lane in the work registry
(`WORK_LANES`), split by plan tier, or by tenant for one moved apart."""


def tier_lane(plan_tier: str) -> str:
    """The loop lane of a plan tier, which the runners of that tier serve."""
    return f"{LOOP_LANE_PREFIX}{plan_tier}"


def own_lane(org_id: UUID) -> str:
    """The loop lane of a tenant whose loops crowd its tier's neighbours."""
    return f"{LOOP_LANE_PREFIX}org:{org_id}"


def loop_lane(org_id: UUID, share: FairShare) -> str:
    return own_lane(org_id) if share.own_lane else tier_lane(share.plan_tier)


def lane_cap(lane: str, tier_shares: Mapping[str, int], default_share: int) -> int:
    """The cap a loop lane passes to the claim: the most loops one tenant
    holds claimed there, unless it has a cap of its own on the lane. A
    tier's lane takes its tier's share, or the default where the tier sets
    none; a tenant's own lane takes the default."""
    rest = lane.removeprefix(LOOP_LANE_PREFIX)
    if rest.startswith("org:"):
        return default_share
    return tier_shares.get(rest, default_share)


OWN_LANES = "(own)"
"""The label the depth gauge gives every tenant's own lane together: a lane
of one tenant is that tenant's view, an operator-plane read, never a label.
No plan tier is spelled so."""


def tier_label(lane: str) -> str | None:
    """The plan tier a loop lane's depth is labelled with: the tier of a
    tier's lane, and `OWN_LANES` for a tenant's own; None for a lane that is
    no loop lane."""
    if not lane.startswith(LOOP_LANE_PREFIX):
        return None
    rest = lane.removeprefix(LOOP_LANE_PREFIX)
    return OWN_LANES if rest.startswith("org:") else rest


PARK_AGES: tuple[tuple[str, timedelta], ...] = (
    ("under_1h", timedelta(hours=1)),
    ("under_1d", timedelta(days=1)),
)
"""The age labels of the parks gauge, by how long ago a parked session last
changed, and the cut each one ends at; past the last cut, `PARK_OLDEST`."""
PARK_OLDEST = "over_1d"


def park_age_label(passed: int) -> str:
    """The label of a session that is past `passed` of the cuts."""
    return PARK_AGES[passed][0] if passed < len(PARK_AGES) else PARK_OLDEST


def host_lane(host_id: UUID) -> str:
    """A host's lane: what runs in a workspace it holds."""
    return f"host:{host_id}"


def pool_lane(pool_id: UUID) -> str:
    """A pool's lane: a workspace any host of the pool may prepare."""
    return f"pool:{pool_id}"
