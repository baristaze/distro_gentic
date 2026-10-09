"""A tenant's fair share of the loops: the plan tier whose lane its loops
run in, and whether they run in a lane of their own instead. How many of
them run at once is the work queue's cap on that lane: the tier's share,
or the tenant's own cap where an operator set one."""

from typing import Annotated

from pydantic import Field, StringConstraints

from acme.om.base import Identifiable, Platform, Trackable
from acme.om.work.types.tenant_cap import MAX_CAP

PlanTier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,31}$")]
"""A plan tier's name: a lane's name holds it, so it is short and plain."""


class TierShare(Platform):
    """A plan tier's share: the most loops one tenant holds claimed on the
    tier's lane, the cap its runners pass to the claim."""

    tier: PlanTier
    share: int = Field(ge=1, le=MAX_CAP)


class FairShare(Identifiable, Trackable):
    """One row a tenant, which the platform's operators write; a tenant with
    none has the default tier (`PlacementOptions`)."""

    plan_tier: PlanTier
    own_lane: bool = False  # its loops crowd its tier's neighbours
    version: int = 1


class ShareStanding(Platform):
    """A tenant's share as an operator reads it: its row, and the most of
    its loops that run at once on its lane, which the claim holds. That is
    its own cap where an operator set one (`own_cap`), and its lane's
    otherwise."""

    share: FairShare
    concurrency: int
    own_cap: bool
