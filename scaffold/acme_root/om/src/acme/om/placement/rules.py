"""Pure rules of the placement namespace: the lane each kind of work goes
to, the lanes and kinds a claimant's identity claims, and the fair share's
guard, and the bounded labels of the platform's gauges. Values in, values
out; no clock, no storage, no settings."""

from collections.abc import Mapping
from datetime import timedelta
from uuid import UUID

from acme.om.placement.types.claimant import Claimant
from acme.om.placement.types.share import FairShare
from acme.om.placement.types.work import ExecPayload, WorkspaceOperation, WorkspacePayload
from acme.om.work.types.work_item import WorkKind

DEFAULT_TIER = "standard"
"""The plan tier of a tenant no operator has given one."""

LOOP_LANE_PREFIX = "loop:"

CLAIMED_THROUGH_THE_GATEWAY: frozenset[WorkKind] = frozenset({WorkKind.EXEC, WorkKind.WORKSPACE})
"""The kinds a host claims through the gateway (`claims_of`), which no
worker of the platform's own handles."""


def tier_lane(plan_tier: str) -> str:
    """The loop lane of a plan tier, which the runners of that tier serve."""
    return f"{LOOP_LANE_PREFIX}{plan_tier}"


def own_lane(org_id: UUID) -> str:
    """The loop lane of a tenant whose loops crowd its tier's neighbours."""
    return f"{LOOP_LANE_PREFIX}org:{org_id}"


def loop_lane(org_id: UUID, share: FairShare) -> str:
    return own_lane(org_id) if share.own_lane else tier_lane(share.plan_tier)


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


def placed_lane(kind: WorkKind, payload: Mapping[str, object]) -> str | None:
    """The lane where a kind a host runs goes, read off its
    payload; None for every other kind. The payload is the shape
    `WORK_PAYLOADS` fixes for the kind, which the enqueue holds it to."""
    if kind is WorkKind.EXEC:
        return host_lane(ExecPayload.model_validate(payload).host_id)
    if kind is WorkKind.WORKSPACE:
        workspace = WorkspacePayload.model_validate(payload)
        if workspace.operation is WorkspaceOperation.PREPARE:
            assert workspace.pool_id is not None  # the payload's own rule
            return pool_lane(workspace.pool_id)
        assert workspace.host_id is not None
        return host_lane(workspace.host_id)
    return None


def claims_of(claimant: Claimant) -> tuple[tuple[str, tuple[WorkKind, ...]], ...]:
    """The lanes a claimant takes work from, in the order it takes it, and
    the kinds it takes from each, all read off its identity. A host runs
    what its workspaces need first, then prepares one for its pool."""
    return (
        (host_lane(claimant.id), (WorkKind.EXEC, WorkKind.WORKSPACE)),
        (pool_lane(claimant.pool_id), (WorkKind.WORKSPACE,)),
    )


def admits(ahead: int, concurrency: int) -> bool:
    """Whether a claimed loop may run: fewer of its tenant's loops are
    running ahead of it than its share allows."""
    return ahead < concurrency
