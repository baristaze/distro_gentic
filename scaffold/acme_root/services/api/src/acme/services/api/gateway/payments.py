"""What a posted payment carries into its route: the payment provider's
confirmation, byte for byte, and its signature header. The gateway reads
them, and agent billing checks the one against the other before anything is
credited."""

from typing import Annotated

from fastapi import Depends, Header, Request

from acme.services.api.services.webhooks import SignedDelivery

PAYMENT_SIGNATURE = "Payment-Signature"
"""The header that carries the payment provider's signature over the body."""


async def payment_delivery(
    request: Request,
    signature: Annotated[str | None, Header(alias=PAYMENT_SIGNATURE)] = None,
) -> SignedDelivery:
    return SignedDelivery(payload=await request.body(), signature=signature)


PaymentDelivery = Annotated[SignedDelivery, Depends(payment_delivery)]
