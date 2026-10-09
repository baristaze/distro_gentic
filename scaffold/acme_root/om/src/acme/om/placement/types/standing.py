"""What the operator plane answers of where one session's work stands and
what one host is handed, and the counts across every tenant the sweep
draws as the platform's gauges. Every field is an id, a name the platform
chose, a count, a time, or a state: never what a tenant wrote."""

from datetime import datetime
from uuid import UUID

from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.base import Platform
from acme.om.hosts.rules import HostState
from acme.om.hosts.types.host import Advertisement
from acme.om.steps.types.header import Park
from acme.om.work.types.work_item import WorkStatus


class LoopStanding(Platform):
    """The session's loop item made last, as the queue holds it, and its
    place in line: the ready items before it on its lane, any tenant's, and
    the tenant's loops running ahead of it, which the claim holds to the
    tenant's cap."""

    item_id: UUID
    status: WorkStatus
    lane: str
    attempts: int
    max_attempts: int
    available_at: datetime
    claimed_by: str | None
    lease_expires_at: datetime | None
    ready_ahead: int
    running_ahead: int


class SessionStanding(Platform):
    """Why one session is or is not moving: its status and its park, its
    last change (when it parked, for a parked one), its tenant's share,
    where it runs, and its loop. `concurrency` is the cap the claim holds
    the tenant to on its lane: its own where `own_cap`, else the lane's.
    `pool_id` None is the cloud, where `hosts_online` is None; `share_set`
    False is the default tier."""

    session_id: UUID
    status: SessionStatus
    park: Park | None
    changed_at: datetime
    pending_input: bool
    plan_tier: str
    own_lane: bool
    concurrency: int
    own_cap: bool
    share_set: bool
    pool_id: UUID | None
    hosts_online: int | None
    loop: LoopStanding | None


class LaneLoad(Platform):
    """The ready items of one kind on one lane."""

    lane: str
    kind: str  # a registered work kind
    ready: int


class HostStanding(Platform):
    """Why one host takes no work: what it advertised, the version of work
    it reads against the floor, when it last called, and what is ready on
    the lanes it claims from, its pool's and its own."""

    host_id: UUID
    pool_id: UUID
    state: HostState
    revoked: bool
    advertisement: Advertisement
    exec_version: int
    exec_floor: int
    last_seen_at: datetime
    lanes: tuple[LaneLoad, ...]


class Count(Platform):
    """One series of a gauge: its labels, in the gauge's order, and its value."""

    labels: tuple[str, ...]
    value: int


class FleetCounts(Platform):
    """The platform's signals across every tenant, each by bounded labels
    alone: the parked sessions by reason and age, the ready loops by plan
    tier, and the hosts by state."""

    parked: tuple[Count, ...]
    loops_ready: tuple[Count, ...]
    hosts: tuple[Count, ...]
