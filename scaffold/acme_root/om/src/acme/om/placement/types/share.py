"""A tenant's fair share of the loops: the plan tier whose lane its loops
run in, whether they run in a lane of their own instead, and how many of
them run at once."""

from typing import Annotated

from pydantic import Field, StringConstraints

from acme.om.base import Identifiable, Trackable

PlanTier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,31}$")]
"""A plan tier's name: a lane's name holds it, so it is short and plain."""


class FairShare(Identifiable, Trackable):
    """One row a tenant, which the platform's operators write; a tenant with
    none has the default share (`PlacementOptions`)."""

    plan_tier: PlanTier
    own_lane: bool = False  # its loops crowd its tier's neighbours
    concurrency: int = Field(ge=1)  # the most of its loops that run at once
    version: int = 1
