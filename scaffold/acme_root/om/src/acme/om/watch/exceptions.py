"""The refusals of the watch."""

from acme.om.exceptions import NotAuthenticated, PlatformException, PreconditionFailed


class WatchException(PlatformException): ...


class LiveReadRefused(WatchException, NotAuthenticated):
    """A live read whose handle does not verify, or has expired. It reads
    nothing; the viewer asks for a new handle."""

    code = "live_read_refused"


class NotHandedOver(WatchException, PreconditionFailed):
    """A command by hand on a session whose agent holds its workspace. The
    person takes control first, so the two never act there at once."""

    code = "not_handed_over"


class CommandRunning(WatchException, PreconditionFailed):
    """A giving back while a command of the person's still runs, which would
    run beside the agent's next ones. The person waits for it to end, or
    gives back with `stop`."""

    code = "command_running"
