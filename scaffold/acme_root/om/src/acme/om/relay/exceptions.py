"""The refusals of the relay."""

from acme.om.exceptions import (
    Conflict,
    NotAuthorized,
    PlatformException,
    PreconditionFailed,
    Unavailable,
)


class RelayException(PlatformException): ...


class StaleExec(RelayException, PreconditionFailed):
    """A command, or a stop, from a run that no longer holds the session:
    its writer epoch is below the session's. Nothing it asks for runs."""

    code = "stale_exec"


class ItemNotHeld(RelayException, Conflict):
    """A host's push, read, or renewal for an item it does not hold under a
    live claim: another host's, one settled already, or one whose lease ran
    out. It lands nothing."""

    code = "exec_not_held"


class NoWorkspaceHost(RelayException, NotAuthorized):
    """A call of a session pinned to its tenant's hosts while no host holds
    its workspace. It is refused, never run on one of the platform's own
    machines instead."""

    code = "no_workspace_host"


class ContentNotKept(RelayException, Unavailable):
    """A call whose session keeps no content at rest: its command would rest
    in the control plane until its host read it, so it is not relayed."""

    code = "content_not_kept"
