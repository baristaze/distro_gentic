"""Pure rules of the hosts namespace: the prefixes of a host's two
credentials, the versions of the wire types a host or a daemon reads and
their floors, when a host counts as online, and how a rotation ends the
credential it replaces. Values in, values out; no clock, no storage, no
settings."""

from datetime import datetime, timedelta
from enum import StrEnum

from acme.om.hosts.types.host import Host

ENROLLMENT_PREFIX = "hen_"
"""An enrollment token's prefix. It enrolls a host and does nothing else."""

HOST_CREDENTIAL_PREFIX = "hst_"
"""A host credential's prefix, a kind of its own: the gateway's tenant
transitions know no such prefix and refuse it, and the host routes refuse
every other."""


class WireType(StrEnum):
    """The work a machine outside the platform's processes reads off the wire:
    public types, versioned like any other."""

    EXEC = "exec"  # what a workspace host runs: commands, file operations, workspaces
    STATION = "station"  # what a station's daemon runs


WIRE_VERSION: dict[WireType, int] = {WireType.EXEC: 1, WireType.STATION: 1}
"""The version of each wire type this build writes."""

WIRE_FLOOR: dict[WireType, int] = {WireType.EXEC: 1, WireType.STATION: 1}
"""The oldest version of each wire type this build still hands work to. A
breaking change to a type ships as its next version and raises its floor
only once the hosts in the field read it, since a customer upgrades on its
own schedule."""


def at_or_above_floor(wire: WireType, version: int) -> bool:
    """Whether a machine that reads `version` of the wire type may be handed
    work of it."""
    return version >= WIRE_FLOOR[wire]


def online(host: Host, now: datetime, window: timedelta) -> bool:
    """A host is online while it called within the window, is not revoked,
    and reads `exec` work at or above the floor: a host that may not be
    handed work does not count as one that serves its pool."""
    return (
        host.revoked_at is None
        and host.last_seen_at > now - window
        and at_or_above_floor(WireType.EXEC, host.exec_version)
    )


class HostState(StrEnum):
    """A host as the platform's gauge counts it: the label is bounded, and a
    host's own view is an operator-plane read."""

    ONLINE = "online"  # called within the window, at or above the floor
    OFFLINE = "offline"  # silent past the window
    BELOW_FLOOR = "below_floor"  # reads a version of `exec` work below the floor


def host_state(seen: bool, at_floor: bool) -> HostState:
    """The state a count of hosts is labelled with: a host below the floor
    is that first, whether it calls or not, since no work reaches it."""
    if not at_floor:
        return HostState.BELOW_FLOOR
    return HostState.ONLINE if seen else HostState.OFFLINE


def retired_at(expires_at: datetime, now: datetime, grace: timedelta) -> datetime:
    """When a rotated credential ends: after the grace, so a call in flight
    with it still lands, and never later than it would have. It does not
    rotate again in the grace: a credential rotates once."""
    return min(expires_at, now + grace)
