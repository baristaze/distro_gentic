"""Wire types of placement: a tenant's fair share, and where one of its
sessions' work and one of its hosts stand, as an operator reads them."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.agent_sessions.types.agent_session import AgentSessionStatus
from acme.om.placement.types.share import PlanTier
from acme.om.work.types.tenant_cap import MAX_CAP
from acme.om.work.types.work_item import WorkStatus
from acme.services.api.types.agent_sessions import ParkView
from acme.services.api.types.common import RequestBody, View


class SetShareRequest(RequestBody):
    """A tenant's fair share: the plan tier whose lane its loops run in,
    whether they run in a lane of their own instead, and how many of them
    run at once there, its own cap, which holds in place of its tier's
    share. With no `concurrency`, the tier's share holds."""

    plan_tier: PlanTier
    own_lane: bool = False
    concurrency: int | None = Field(default=None, ge=1, le=MAX_CAP)


class ShareView(View):
    """A tenant's fair share as the operator wrote it, at its version.
    `concurrency` is the most of its loops that run at once on its lane:
    its own cap where `own_cap`, else its tier's share."""

    org_id: UUID
    plan_tier: str
    own_lane: bool
    concurrency: int
    own_cap: bool
    version: int
    updated_at: datetime
    updated_by: UUID


class LoopStandingView(View):
    """The session's loop item made last, and its place in line:
    `ready_ahead` items of any tenant are ready before it on its lane, and
    `running_ahead` of its tenant's loops run ahead of it on that lane,
    which the claim holds to the tenant's cap there."""

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
    when it parked, for a parked one. `concurrency` is the cap the claim
    holds its tenant to on the lane its loop stands on, or, with no loop,
    the lane its next goes to: its own where `own_cap`, else the lane's.
    `pool_id` null is the cloud, where `hosts_online` is null; `share_set`
    false is the default tier."""

    agent_session_id: UUID
    status: AgentSessionStatus
    park: ParkView | None
    changed_at: datetime
    pending_input: bool
    plan_tier: str
    own_lane: bool
    concurrency: int
    own_cap: bool
    share_set: bool
    pool_id: UUID | None
    hosts_online: int | None
    loop: LoopStandingView | None
