"""A station and where it stands: the lab whose daemon reaches it, and the
pool of stations of its kind. A station's row is the lease store's anchor:
the highest token granted on it, and the lease that holds it until when.
Its limits are none of the platform's: they live on the station's host."""

from datetime import datetime
from typing import Annotated, ClassVar
from uuid import UUID

from pydantic import Field, StringConstraints

from acme.om.base import Identifiable, Trackable

StationName = Annotated[str, StringConstraints(min_length=1, max_length=64)]

Capability = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,62}$")]
"""What a station can do, as its owner names it: `arm`, `gripper.v2`."""


class Lab(Identifiable, Trackable):
    """The place one station daemon serves, inside a tenant's wall. Its
    stations are reached through that daemon alone, and their work goes to
    the lab's lane."""

    name: StationName


class StationPool(Identifiable, Trackable):
    """Stations of one kind, and the line any of them may serve.
    `job_seconds` is the declared length of one holding, which a place's
    estimate reads."""

    name: StationName
    job_seconds: int = Field(default=600, ge=1, le=7 * 24 * 3600)


class Station(Identifiable, Trackable):
    """One station of a lab, in a pool. `hold_seconds` is how long a lease
    outlives its last job while its session is parked. The last three
    fields are the lease store's: the highest fencing token granted on the
    station, and the lease that holds it until `held_until`."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = ("token", "lease_id", "held_until")

    lab_id: UUID
    pool_id: UUID
    name: StationName
    capabilities: tuple[Capability, ...] = ()
    hold_seconds: int = Field(default=300, ge=1, le=24 * 3600)
    token: int = Field(default=0, ge=0)
    lease_id: UUID | None = None
    held_until: datetime | None = None
