"""The webhooks service: the edge of a provider's deliveries. The check, then
the queue; what a delivery means is the worker's to apply."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field

from acme.om.context import RequestContext
from acme.services.api.types.webhooks import DeliveryReceivedView


@dataclass(frozen=True)
class SignedDelivery:
    """What an inbound delivery carries in: its body exactly as it arrived,
    which is what the signature is over, and the provider's signature
    header, which the gateway reads."""

    payload: bytes
    signature: str | None
    headers: Mapping[str, str] = field(default_factory=dict[str, str])
    """Every header the delivery carried, its name in lower case, for an
    integration whose signature rides in a header of its own."""


class WebhooksServiceInterface(ABC):
    @abstractmethod
    async def receive_identity(
        self, rctx: RequestContext, delivery: SignedDelivery
    ) -> DeliveryReceivedView:
        """Checks the identity provider's signature over the body and its
        timestamp, then queues the delivery by the request's deadline. A
        delivery that fails the check is refused before anything is
        queued."""
        ...

    @abstractmethod
    async def receive_integration(
        self, rctx: RequestContext, name: str, delivery: SignedDelivery
    ) -> DeliveryReceivedView:
        """An integration's event: the integration checks its signature over
        the body and its timestamp and reads it, then the event is queued for
        the router under a key over the integration and the delivery's id,
        named with what served it, the integration's word and never the
        body's. A delivery that fails the check, or that names no
        installation of the platform or no event, is refused before anything
        is queued; an integration this process has none of is unavailable."""
        ...
