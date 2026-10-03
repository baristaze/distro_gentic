"""Wire types of the provider webhook ingress."""

from acme.services.api.types.common import View


class DeliveryReceivedView(View):
    """The delivery checked out and is queued, or, for the system's check of
    this address, answered with the challenge it sent; the provider stops
    retrying."""

    received: bool
    challenge: str | None = None
