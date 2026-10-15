"""The refusals of the cloud pool swimlane."""

from acme.om.exceptions import Conflict, OmException


class CloudPoolException(OmException): ...


class VmUnbound(CloudPoolException, Conflict):
    """A VM of the cloud pool that serves no session yet: a warm one,
    started ahead of the session that will claim it. Its host asks again a
    little later, with the same key."""

    code = "vm_unbound"
