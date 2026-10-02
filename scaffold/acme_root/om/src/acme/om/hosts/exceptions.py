"""The refusals of the hosts swimlane."""

from acme.om.exceptions import NotAuthorized, PlatformException


class HostsException(PlatformException): ...


class VersionBelowFloor(HostsException):
    """A host that reads a version of a wire type below the one the platform
    still writes is handed no work: it upgrades, then claims."""

    http_status = 426
    code = "version_below_floor"


class PinnedToHosts(HostsException, NotAuthorized):
    """A call of a session pinned to a host pool, with no host of the pool
    named to run it. It is refused, so the model reads why, and it is never
    run on one of the platform's own machines instead."""

    code = "pinned_to_hosts"
