"""The line: a session's ask for a station, its place among the others,
and what it is bound to. A session asks for one station, or for any
station of a pool with the capabilities it needs; each pool and each
station has a line, and a station's own line and its pool's are served
together, in rank order."""

from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import Field

from acme.om.attribution.types.principal import Principal
from acme.om.base import Identifiable, Platform, Trackable
from acme.om.evidence.types.record import NAME, PROJECT, VERSION
from acme.om.stations.types.station import Capability


class EntryState(StrEnum):
    WAITING = "waiting"  # in line
    GRANTED = "granted"  # a lease was granted to it
    LEFT = "left"  # it left the line, or its session no longer waited


class StationAsk(Platform):
    """What a session asks for, and what it binds: the candidate under
    test, the procedure to run, and the pool. The approval the call that
    asks needs is the engine's, asked before it runs, and it binds these
    three; every job under the lease a grant gives runs this procedure on
    this candidate and nothing else."""

    session_id: UUID
    pool_id: UUID
    station_id: UUID | None = None  # one station of the pool, or any that serves
    capabilities: tuple[Capability, ...] = Field(default=(), max_length=32)
    project: str = Field(pattern=PROJECT)
    candidate: str = Field(pattern=VERSION)  # the version under test
    procedure: str = Field(pattern=NAME)
    procedure_version: str = Field(pattern=VERSION)


class LineEntry(Identifiable, Trackable):
    """One ask in line. `principal` is who asked, whose authority the
    grant's event arrives on. `rank` orders a pool's line, the station
    lines in it included: lower goes first, and a person who manages the
    stations may move an entry."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = ("rank", "state", "lease_id", "settled_at")

    session_id: UUID
    pool_id: UUID
    station_id: UUID | None = None
    capabilities: tuple[Capability, ...] = ()
    project: str = Field(pattern=PROJECT)
    candidate: str = Field(pattern=VERSION)
    procedure: str = Field(pattern=NAME)
    procedure_version: str = Field(pattern=VERSION)
    principal: Principal
    rank: float
    state: EntryState = EntryState.WAITING
    lease_id: UUID | None = None
    settled_at: datetime | None = None  # when it was granted, or left


class LinePlace(Platform):
    """An entry as its session sees it: how many wait ahead of it, and an
    estimate of the wait, in seconds, from the pool's declared holding."""

    entry: LineEntry
    position: int = Field(ge=0)
    estimate_seconds: int = Field(ge=0)
