"""The payment provider of a process that takes no payment: every
confirmation is refused, naming why, so no credit is ever posted on its
word."""

from datetime import datetime

from acme.integrations.exceptions import DeliveryRefused
from acme.integrations.payments import PaymentConfirmation, PaymentProviderInterface


class PaymentProviderAbsentImpl(PaymentProviderInterface):
    def verify_confirmation(
        self, payload: bytes, signature: str | None, now: datetime
    ) -> PaymentConfirmation:
        raise DeliveryRefused("no payment provider is configured, so no payment is confirmed")

    def describe(self) -> str:
        return "payments=absent"
