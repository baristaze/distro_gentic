import json
from collections.abc import Callable
from datetime import datetime

from acme.infra.queues import Queues, QueuesInterface
from acme.integrations.events import IntegrationInterface
from acme.integrations.exceptions import DeliveryRefused
from acme.integrations.identity import IdentityProviderInterface
from acme.om.base import utcnow
from acme.om.context import RequestContext
from acme.om.evidence.types.provenance import Provenance
from acme.om.exceptions import ValidationFailed
from acme.om.intake.rules import event_of
from acme.services.api.services.webhooks import SignedDelivery, WebhooksServiceInterface
from acme.services.api.types.webhooks import DeliveryReceivedView


class WebhooksServiceImpl(WebhooksServiceInterface):
    """The edge of an outside producer: the check, then the queue. What the
    delivery means is the worker's to apply, under the org it names."""

    def __init__(
        self,
        identity: IdentityProviderInterface,
        queues: QueuesInterface,
        integrations: Callable[[str], IntegrationInterface],
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._identity = identity
        self._queues = queues
        self._integrations = integrations
        self._clock = clock

    async def receive_identity(
        self, rctx: RequestContext, delivery: SignedDelivery
    ) -> DeliveryReceivedView:
        verified = self._identity.verify_delivery(delivery.payload, delivery.signature)
        body = {
            "idempotency_key": str(verified.key),
            "provider": "identity",
            "delivery": verified.model_dump(mode="json"),
        }
        await self._queues.send(
            Queues.WEBHOOKS, json.dumps(body).encode("utf-8"), deadline=rctx.deadline
        )
        return DeliveryReceivedView(received=True)

    async def receive_integration(
        self, rctx: RequestContext, name: str, delivery: SignedDelivery
    ) -> DeliveryReceivedView:
        integration = self._integrations(name)
        provided = integration.verify_delivery(delivery.payload, delivery.headers, self._clock())
        try:
            org_id, event = event_of(name, Provenance(integration.provenance), provided)
        except ValidationFailed as refused:
            raise DeliveryRefused(refused.message) from None
        # The shape the worker's feedback consumer reads: the org, and the event.
        body = {
            "idempotency_key": str(event.id),
            "provider": "feedback",
            "delivery": {"org_id": str(org_id), "event": event.model_dump(mode="json")},
        }
        await self._queues.send(
            Queues.WEBHOOKS, json.dumps(body).encode("utf-8"), deadline=rctx.deadline
        )
        return DeliveryReceivedView(received=True)
