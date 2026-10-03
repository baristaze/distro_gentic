"""What an inbound delivery carries into a route: its body, byte for byte,
and the provider's signature header. The gateway reads them, and the
service checks the one against the other before anything is queued."""

from typing import Annotated

from fastapi import Depends, Header, Request

from acme.integrations.identity.deliveries import SIGNATURE_HEADER
from acme.services.api.services.webhooks import SignedDelivery


async def identity_delivery(
    request: Request,
    signature: Annotated[str | None, Header(alias=SIGNATURE_HEADER)] = None,
) -> SignedDelivery:
    return SignedDelivery(payload=await request.body(), signature=signature)


IdentityDelivery = Annotated[SignedDelivery, Depends(identity_delivery)]


async def integration_delivery(request: Request) -> SignedDelivery:
    """An integration's delivery: its body, and every header it carried, since
    each integration signs in a header of its own."""
    headers = {name.lower(): value for name, value in request.headers.items()}
    return SignedDelivery(payload=await request.body(), signature=None, headers=headers)


IntegrationDelivery = Annotated[SignedDelivery, Depends(integration_delivery)]
