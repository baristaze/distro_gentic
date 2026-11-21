"""The refusals of the hosts swimlane."""

from acme.om.exceptions import Conflict, NotAuthorized, OmException


class HostsException(OmException): ...


class VersionBelowFloor(HostsException):
    """A host that reads a version of a wire type below the one the platform
    still writes is handed no work: it upgrades, then claims."""

    http_status = 426
    code = "version_below_floor"


class PinnedToHosts(HostsException, NotAuthorized):
    """A call of a session pinned to a host pool, with no host of the pool
    named to run it. It is refused, so the model reads why, and it is never
    run on one of the platform's own VMs instead."""

    code = "pinned_to_hosts"


class WorkspaceHeldElsewhere(HostsException, Conflict):
    """A client asked to serve a session's workspace that is not its
    person's own local one: a VM of the cloud pool, a host of a pool, or no
    host at all holds it, or another person's client serves it. The client
    serves nothing, and follows the session instead."""

    code = "workspace_held_elsewhere"
