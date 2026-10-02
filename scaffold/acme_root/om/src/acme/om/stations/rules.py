"""Pure rules of the stations namespace: the daemon credential's prefix,
the park a session waits in line on, when a station is free, which
station serves which ask, the line's order and a place's estimate, and the
words a grant and a revoke reach a session with. Values in, values out;
no clock, no storage, no settings."""

import math
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from acme.om.agent_sessions.types.agent_session import AgentSession, SessionStatus
from acme.om.stations.types.lease import StationLease
from acme.om.stations.types.line import EntryState, LineEntry, LinePlace
from acme.om.stations.types.station import Station
from acme.om.steps.types.header import Park, ParkReason

DAEMON_CREDENTIAL_PREFIX = "std_"
"""A station daemon's credential prefix, a kind of its own: the tenant's
transitions and the hosts' know no such prefix and refuse it, and the
daemon's routes refuse every other."""

LINE_PARK = Park(reason=ParkReason.RESOURCE, unlock="station")
"""The park of a session waiting in a station's line, which a grant
unlocks. It names no time: the grant is what clears it."""


def waits(session: AgentSession) -> bool:
    """Whether a session waits in line now: parked on the line's park."""
    return session.status is SessionStatus.PARKED and session.park == LINE_PARK


def no_longer_waits(session: AgentSession) -> bool:
    """Whether a session stopped waiting for good: its loop ended, or it is
    parked on something else. A session that runs, or is about to, has not
    parked yet and keeps its place, and a waiting one keeps it too."""
    if session.status is SessionStatus.IDLE:
        return True
    return session.status is SessionStatus.PARKED and session.park != LINE_PARK


def free(station: Station, now: datetime, margin: timedelta) -> bool:
    """Whether a station may be granted: no lease holds it, or the one that
    did ran out more than the margin ago. The margin covers the clocks of
    the processes that grant, and the time the daemon's last answer took on
    the way, so a daemon that times its lease on its own clock stops before
    the station is granted again."""
    return station.held_until is None or station.held_until + margin <= now


def serves(station: Station, entry: LineEntry) -> bool:
    """Whether a station answers an ask: it is the station asked for, or one
    of the pool asked for, with every capability the ask needs."""
    if entry.pool_id != station.pool_id:
        return False
    if entry.station_id is not None and entry.station_id != station.id:
        return False
    return set(entry.capabilities) <= set(station.capabilities)


def in_line_order(entries: Iterable[LineEntry]) -> list[LineEntry]:
    """The order a line is served in: by rank, then by when an entry was
    made, which its id carries."""
    return sorted(entries, key=lambda entry: (entry.rank, entry.id))


def rank_between(before: float | None, after: float | None, fallback: float) -> float:
    """The rank of an entry moved between two others: `before` is the rank
    of the one it follows, `after` of the one it goes ahead of, None at
    either end of the line. An empty line takes `fallback`."""
    if before is None and after is None:
        return fallback
    if before is None:
        assert after is not None
        return after - 1.0
    if after is None:
        return before + 1.0
    return (before + after) / 2


def competes(ahead: LineEntry, entry: LineEntry) -> bool:
    """Whether an entry ahead may take a station `entry` waits for: either
    takes any station of the pool, or both ask for the same one."""
    return (
        ahead.station_id is None or entry.station_id is None or ahead.station_id == entry.station_id
    )


def place(entry: LineEntry, line: Sequence[LineEntry], serving: int, job_seconds: int) -> LinePlace:
    """An entry's place: the waiting entries ahead of it that compete for
    what it waits for, and an estimate of its wait from the pool's declared
    holding, shared among the stations that serve it."""
    if entry.state is not EntryState.WAITING:
        return LinePlace(entry=entry, position=0, estimate_seconds=0)
    ordered = in_line_order(line)
    key = (entry.rank, entry.id)
    position = sum(
        1
        for other in ordered
        if other.id != entry.id
        and other.state is EntryState.WAITING
        and (other.rank, other.id) < key
        and competes(other, entry)
    )
    rounds = math.ceil((position + 1) / max(1, serving))
    return LinePlace(entry=entry, position=position, estimate_seconds=rounds * job_seconds)


def seconds_left(expires_at: datetime, now: datetime) -> float:
    """How long a lease has left, as the daemon is told it: a duration."""
    return max(0.0, (expires_at - now).total_seconds())


def renewed_until(current: datetime, now: datetime, length: timedelta) -> datetime:
    """A renewal's new end: never sooner than the end it has."""
    return max(current, now + length)


def retired_at(expires_at: datetime, now: datetime, grace: timedelta) -> datetime:
    """When a rotated daemon credential ends: after the grace, so a call in
    flight with it still lands, and never later than it would have. It does
    not rotate again in the grace: a credential rotates once."""
    return min(expires_at, now + grace)


def grant_text(station: Station, lease: StationLease, seconds: float) -> str:
    """What the event that wakes a granted session says."""
    return (
        f"Station {station.name} ({station.id}) is granted to this session: lease "
        f"{lease.id}, fencing token {lease.token}. It is held {int(seconds)} seconds "
        "while this session waits, and renewed while a job runs. Send jobs under the "
        "lease, and release it when done."
    )


def revoke_text(lease: StationLease) -> str:
    """What the event that tells a session its lease was revoked says."""
    return (
        f"The lease {lease.id} on station {lease.station_id} was revoked by a person who "
        "manages the stations. The station takes its controlled stop, and no job runs "
        "under the lease again."
    )
