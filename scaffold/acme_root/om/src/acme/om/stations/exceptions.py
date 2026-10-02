"""The refusals of the stations swimlane."""

from acme.om.exceptions import Conflict, PlatformException


class StationsException(PlatformException): ...


class LeaseEnded(StationsException):
    """A lease that ran out, was released, or was revoked. Gone, not a
    conflict: asking again never brings it back. The daemon that reads it
    takes the station's controlled stop."""

    http_status = 410
    code = "lease_ended"


class JobSettled(StationsException, Conflict):
    """A station job that is not where the call needs it: claimed again
    after it ran, or reported with another run than the one recorded. A job
    runs once."""

    code = "job_settled"
