"""The trust swimlane's refusals, each in a shape of the platform's root."""

from acme.om.exceptions import NotAuthorized, PlatformException, ValidationFailed


class TrustException(PlatformException): ...


class SecretCrossesWall(TrustException, NotAuthorized):
    """A secret that would be resolved on the far side of the session's
    wall: a cloud secret for a session inside a customer's wall, or a secret
    held inside the wall for a session in the cloud. Named, never shown."""

    code = "secret_crosses_wall"


class ContentNotGranted(TrustException, NotAuthorized):
    """An operator asked for a session's content without a live grant of
    the content permission in that tenant: `read` alone never opens it."""

    code = "content_not_granted"


class KeyRefused(TrustException, ValidationFailed):
    """The provider refused a key when it was probed, so it is not saved."""

    code = "key_refused"
