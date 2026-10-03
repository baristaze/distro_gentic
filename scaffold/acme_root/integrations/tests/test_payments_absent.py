"""The payment provider of a process that takes no payment refuses every
confirmation, even one the twin signed."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from acme.integrations.exceptions import DeliveryRefused
from acme.integrations.payments.absent import PaymentProviderAbsentImpl
from acme.integrations.payments.twin import PaymentProviderTwinImpl


def test_no_confirmation_checks_out_where_no_provider_is_configured() -> None:
    now = datetime(2026, 10, 3, tzinfo=UTC)
    payload, signature = PaymentProviderTwinImpl().confirm(uuid4(), 1_000_000, now)
    with pytest.raises(DeliveryRefused, match="no payment provider"):
        PaymentProviderAbsentImpl().verify_confirmation(payload, signature, now)
