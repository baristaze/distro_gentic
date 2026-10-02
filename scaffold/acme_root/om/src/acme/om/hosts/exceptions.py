"""The refusals of the hosts swimlane."""

from acme.om.exceptions import PlatformException


class HostsException(PlatformException): ...


class VersionBelowFloor(HostsException):
    """A host that reads a version of a wire type below the one the platform
    still writes is handed no work: it upgrades, then claims."""

    http_status = 426
    code = "version_below_floor"
