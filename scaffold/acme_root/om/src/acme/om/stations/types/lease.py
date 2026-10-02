"""A station lease: a time-limited, renewable right to one station, with a
fencing token that grows with every grant of that station. It is the
session's, and no work item's: a work item's lease is the queue's."""

from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import Field

from acme.om.base import Identifiable, Platform, Trackable


class LeaseEnd(StrEnum):
    RELEASED = "released"  # its session let it go
    REVOKED = "revoked"  # a person who manages the stations ended it
    EXPIRED = "expired"  # it ran out, and the station was granted again


class StationLease(Identifiable, Trackable):
    """One grant of one station to one session: an agent session that
    waited in line, named by `entry_id`, or a validation session, which
    stands in no line and has none. `token` is the station's count of
    grants at this one, so a later grant's is always greater. A live lease
    has no end; it is renewed by the daemon during a job, and while an
    agent session is parked it lasts the station's hold time."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = ("expires_at", "ended_at", "ended")

    station_id: UUID
    lab_id: UUID
    pool_id: UUID
    entry_id: UUID | None
    session_id: UUID
    token: int = Field(ge=1)
    expires_at: datetime
    ended_at: datetime | None = None
    ended: LeaseEnd | None = None


class LeaseTime(Platform):
    """How long a lease has left, as the daemon reads it: a duration, never
    an instant, since the daemon times it on its own monotonic clock."""

    lease_id: UUID
    token: int
    seconds: float = Field(ge=0)
