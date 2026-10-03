import json
from collections.abc import Callable
from datetime import datetime

from acme.infra.queues import Queues, QueuesInterface
from acme.integrations.events import Acknowledged, IntegrationInterface
from acme.integrations.exceptions import DeliveryRefused
from acme.integrations.identity import IdentityProviderInterface
from acme.om.base import utcnow
from acme.om.context import RequestContext
from acme.om.evidence.types.provenance import Provenance
from acme.om.exceptions import ValidationFailed
from acme.om.intake import IntakeManagerInterface
from acme.om.intake.rules import event_of
from acme.services.api.services.webhooks import SignedDelivery, WebhooksServiceInterface
from acme.services.api.types.webhooks import DeliveryReceivedView


class WebhooksServiceImpl(WebhooksServiceInterface):
    """The edge of an outside producer: the check, then the queue. What the
    delivery means is the worker's to apply, under the org it names: for an
    integration's, the tenant that connected the installation it came
    through."""

    def __init__(
        self,
        identity: IdentityProviderInterface,
        queues: QueuesInterface,
        integrations: Callable[[str], IntegrationInterface],
        intake: IntakeManagerInterface,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._identity = identity
        self._queues = queues
        self._integrations = integrations
        self._intake = intake
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
        if isinstance(provided, Acknowledged):
            # The system's check of this address: answered, and nothing queued.
            return DeliveryReceivedView(received=True, challenge=provided.challenge)
        # The installation is the system's own id: the tenant is the one that
        # connected it, never one the delivery names.
        tenant = await self._intake.tenant_of(rctx, name, provided.installation)
        try:
            org_id, event = event_of(name, Provenance(integration.provenance), provided, tenant)
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
