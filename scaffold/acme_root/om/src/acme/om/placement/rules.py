"""Pure rules of the placement namespace: the lane each kind of work goes
to, the lanes and kinds a claimant's identity claims, and the fair share's
guard. Values in, values out; no clock, no storage, no settings."""

from collections.abc import Mapping
from uuid import UUID

from acme.om.placement.types.claimant import Claimant, ClaimantKind
from acme.om.placement.types.share import FairShare
from acme.om.placement.types.work import (
    ExecPayload,
    StationPayload,
    WorkspaceOperation,
    WorkspacePayload,
)
from acme.om.work.types.work_item import WorkKind

DEFAULT_TIER = "standard"
"""The plan tier of a tenant no operator has given one."""

LOOP_LANE_PREFIX = "loop:"

CLAIMED_THROUGH_THE_GATEWAY: frozenset[WorkKind] = frozenset(
    {WorkKind.EXEC, WorkKind.WORKSPACE, WorkKind.STATION}
)
"""The kinds a host or a daemon claims through the gateway (`claims_of`),
which no worker of the platform's own handles."""


def tier_lane(plan_tier: str) -> str:
    """The loop lane of a plan tier, which the runners of that tier serve."""
    return f"{LOOP_LANE_PREFIX}{plan_tier}"


def own_lane(org_id: UUID) -> str:
    """The loop lane of a tenant whose loops crowd its tier's neighbours."""
    return f"{LOOP_LANE_PREFIX}org:{org_id}"


def loop_lane(org_id: UUID, share: FairShare) -> str:
    return own_lane(org_id) if share.own_lane else tier_lane(share.plan_tier)


def host_lane(host_id: UUID) -> str:
    """A host's lane: what runs in a workspace it holds."""
    return f"host:{host_id}"


def pool_lane(pool_id: UUID) -> str:
    """A pool's lane: a workspace any host of the pool may prepare."""
    return f"pool:{pool_id}"


def lab_lane(lab_id: UUID) -> str:
    """A lab's lane: work on the stations its daemon serves."""
    return f"lab:{lab_id}"


def placed_lane(kind: WorkKind, payload: Mapping[str, object]) -> str | None:
    """The lane where a kind a host or a daemon runs goes, read off its
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
    if kind is WorkKind.STATION:
        return lab_lane(StationPayload.model_validate(payload).lab_id)
    return None


def claims_of(claimant: Claimant) -> tuple[tuple[str, tuple[WorkKind, ...]], ...]:
    """The lanes a claimant takes work from, in the order it takes it, and
    the kinds it takes from each, all read off its identity. A host runs
    what its workspaces need first, then prepares one for its pool; a daemon
    serves its lab."""
    if claimant.kind is ClaimantKind.HOST:
        assert claimant.pool_id is not None  # the identity's own rule
        return (
            (host_lane(claimant.id), (WorkKind.EXEC, WorkKind.WORKSPACE)),
            (pool_lane(claimant.pool_id), (WorkKind.WORKSPACE,)),
        )
    assert claimant.lab_id is not None
    return ((lab_lane(claimant.lab_id), (WorkKind.STATION,)),)


def admits(ahead: int, concurrency: int) -> bool:
    """Whether a claimed loop may run: fewer of its tenant's loops are
    running ahead of it than its share allows."""
    return ahead < concurrency
