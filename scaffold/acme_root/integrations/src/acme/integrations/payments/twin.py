"""The payment provider in memory, for tests and a local stack. It holds a
test key, signs `<timestamp>.<body>` with HMAC-SHA256 under it, and checks a
confirmation the same way, inside a five-minute window and in constant time.
Every reference it mints starts with `twin_`."""

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import ValidationError

from acme.integrations.exceptions import DeliveryRefused
from acme.integrations.payments import PaymentConfirmation, PaymentProviderInterface

TOLERANCE = timedelta(minutes=5)
"""How far a confirmation's timestamp may sit from the time it is checked."""


def sign(payload: bytes, key: str, at: datetime) -> str:
    """The signature header the provider sends with `payload` at `at`."""
    stamp = int(at.timestamp())
    digest = hmac.new(key.encode(), f"{stamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={stamp}, v1={digest}"


def verified(payload: bytes, signature: str | None, key: str, now: datetime) -> PaymentConfirmation:
    """The confirmation, once the check passes; `DeliveryRefused` otherwise.
    The reason names what failed and never the key or the header."""
    if not signature:
        raise DeliveryRefused("no signature")
    try:
        stamp, digest = (part.strip() for part in signature.split(","))
        if not stamp.startswith("t=") or not digest.startswith("v1="):
            raise ValueError
        at = int(stamp[2:])
    except ValueError:
        raise DeliveryRefused("the signature is not t=..., v1=...") from None
    if abs(int(now.timestamp()) - at) > TOLERANCE.total_seconds():
        raise DeliveryRefused("the signature's timestamp is outside the window")
    expected = hmac.new(key.encode(), f"{at}.".encode() + payload, hashlib.sha256).hexdigest()
    given = digest[3:]
    if not given.isascii() or not hmac.compare_digest(given, expected):
        raise DeliveryRefused("the signature did not check out")
    try:
        return PaymentConfirmation.model_validate(json.loads(payload))
    except json.JSONDecodeError, UnicodeDecodeError, ValidationError:
        raise DeliveryRefused("the body is not a payment confirmation") from None


class PaymentProviderTwinImpl(PaymentProviderInterface):
    def __init__(self, key: str | None = None) -> None:
        self._key = key or secrets.token_hex(32)
        self._count = 0

    def confirm(self, org_id: UUID, amount_micros: int, at: datetime) -> tuple[bytes, str]:
        """A payment the twin takes and confirms: the body and the signature
        it delivers, as the real provider would."""
        self._count += 1
        confirmation = PaymentConfirmation(
            reference=f"twin_payment_{self._count}",
            org_id=org_id,
            amount_micros=amount_micros,
            confirmed_at=at,
        )
        payload = confirmation.model_dump_json().encode()
        return payload, sign(payload, self._key, at)

    def verify_confirmation(
        self, payload: bytes, signature: str | None, now: datetime
    ) -> PaymentConfirmation:
        return verified(payload, signature, self._key, now)

    def describe(self) -> str:
        return "payments=twin"
