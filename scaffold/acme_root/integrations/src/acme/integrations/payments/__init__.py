"""The payment provider: the hosted service that takes a tenant's money and
confirms each payment with a signed delivery. A bought credit counts only
once its confirmation checks out: the client's word, or an unsigned event,
is never a payment.

One interface and a deterministic twin (`twin.py`), which holds a test key
and signs its own confirmations with the scheme the check reads. No real
client is wired yet."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.infra.base import InfraModel

MAX_REFERENCE = 200


class PaymentConfirmation(InfraModel):
    """One payment the provider confirms: its own reference, the tenant it
    credits, and the amount, in millionths of the reference currency."""

    reference: str = Field(min_length=1, max_length=MAX_REFERENCE)
    org_id: UUID
    amount_micros: int = Field(gt=0)
    confirmed_at: datetime


class PaymentProviderInterface(ABC):
    @abstractmethod
    def verify_confirmation(
        self, payload: bytes, signature: str | None, now: datetime
    ) -> PaymentConfirmation:
        """The confirmation `payload` carries, once its signature checks out
        under the provider's key inside the replay window at `now`;
        `DeliveryRefused` otherwise, naming what failed and never the key."""
        ...

    @abstractmethod
    def describe(self) -> str: ...
