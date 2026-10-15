"""The world's events, as the maintenance worker applies them from the queue
its integrations' ingress fills: each is routed to the session it names and
fires the tenant's agent automations (`deliveries.DeliveryConsumer` reads
them under the provider name `feedback`)."""

from uuid import UUID

from acme.om.agent_automations import AgentAutomationsManagerInterface
from acme.om.agent_automations.types.agent_automation import Firing
from acme.om.base import OmBase
from acme.om.context import RequestContext, TenantContext
from acme.om.intake import IntakeManagerInterface
from acme.om.intake.rules import described
from acme.om.intake.types.event import FeedbackEvent
from acme.workers.maintenance.deliveries import DeliveryProviderInterface


class FeedbackDelivery(OmBase):
    """An event from an integration, as its ingress queues it once its
    signature is checked: the org the integration's installation belongs
    to, and the event in the platform's one shape."""

    org_id: UUID
    event: FeedbackEvent


class FeedbackDeliveriesImpl(DeliveryProviderInterface[FeedbackDelivery]):
    """The world's events: each is routed to the session it names, by the
    routing table, and then fires the tenant's agent automations with what the
    router answered. Both are keyed by the event, so a copy changes
    nothing."""

    def __init__(
        self, intake: IntakeManagerInterface, agent_automations: AgentAutomationsManagerInterface
    ) -> None:
        self._intake = intake
        self._agent_automations = agent_automations

    def read(self, delivery: object) -> FeedbackDelivery:
        return FeedbackDelivery.model_validate(delivery)

    async def org_of(self, rctx: RequestContext, delivery: FeedbackDelivery) -> UUID | None:
        return delivery.org_id

    async def apply(self, ctx: TenantContext, delivery: FeedbackDelivery) -> bool:
        event = delivery.event
        routed = await self._intake.route(ctx, event)
        firing = Firing(
            event_id=event.id,
            occurred_at=event.occurred_at,
            integration=event.integration,
            arrival=event.arrival.value,
            effect=routed.effect.value,
            caused_by=routed.caused_by,
            platform=routed.platform,
            text=described(event),
        )
        await self._agent_automations.fire(ctx, firing)
        return True
