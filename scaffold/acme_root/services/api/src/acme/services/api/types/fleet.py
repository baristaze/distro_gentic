"""The wire types of the platform's operator routes: a tenant's fair share,
where one of its sessions' work stands, what one of its hosts is handed,
and a session's history as `read` sees it, its shape. Each answers ids,
counts, times, and states; a session's content is the agent sessions'
`StepPageView`, behind a grant of its own."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.hosts.rules import HostState
from acme.om.placement.types.share import PlanTier
from acme.om.steps.types.content import ContentState
from acme.om.steps.types.header import ControlCommand, LoopOutcome, ToolFailure
from acme.om.steps.types.step import Actor, Origin, StepType
from acme.om.work.types.work_item import WorkStatus
from acme.services.api.types.agent_sessions import ParkView
from acme.services.api.types.common import RequestBody, View
from acme.services.api.types.hosts import AdvertisementView


class SetShareRequest(RequestBody):
    """A tenant's fair share: the plan tier whose lane its loops run in,
    whether they run in a lane of their own instead, and how many of them
    run at once."""

    plan_tier: PlanTier
    own_lane: bool = False
    concurrency: int = Field(ge=1, le=10_000)


class ShareView(View):
    """A tenant's fair share as the operator wrote it, at its version."""

    org_id: UUID
    plan_tier: str
    own_lane: bool
    concurrency: int
    version: int
    updated_at: datetime
    updated_by: UUID


class LoopStandingView(View):
    """The session's loop item made last, and its place in line:
    `ready_ahead` items of any tenant are ready before it on its lane, and
    `running_ahead` of its tenant's loops run ahead of it, which the claim
    counts against the share."""

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


class SessionStandingView(View):
    """Why a session is or is not moving. `changed_at` is its last change:
    when it parked, for a parked one. `pool_id` null is the cloud, where
    `hosts_online` is null; `share_set` false is the default share."""

    session_id: UUID
    status: SessionStatus
    park: ParkView | None
    changed_at: datetime
    pending_input: bool
    plan_tier: str
    own_lane: bool
    concurrency: int
    share_set: bool
    pool_id: UUID | None
    hosts_online: int | None
    loop: LoopStandingView | None


class LaneLoadView(View):
    lane: str
    kind: str  # a work kind, the platform's or a product's
    ready: int


class HostStandingView(View):
    """Why a host takes no work: its state, what it advertised, the version
    of `exec` work it reads against the floor, when it last called, and what
    is ready on its pool's lane and its own."""

    host_id: UUID
    pool_id: UUID
    state: HostState
    revoked: bool
    advertisement: AdvertisementView
    exec_version: int
    exec_floor: int
    last_seen_at: datetime
    lanes: list[LaneLoadView]


class StepShapeView(View):
    """One step as an operator's `read` sees it: what it is, who wrote it,
    and the fields of its header a reader acts on, never what it says.
    `content` says whether what it says is kept."""

    id: UUID
    seq: int
    loop_id: UUID
    type: StepType
    actor: Actor
    origin: Origin
    responds_to: UUID | None
    created_at: datetime
    content: ContentState
    tool: str | None
    failure: ToolFailure | None
    command: ControlCommand | None
    park: ParkView | None
    outcome: LoopOutcome | None


class ShapePageView(View):
    """One page of a session's shape, after the seq the request named."""

    items: list[StepShapeView]
    has_more: bool
