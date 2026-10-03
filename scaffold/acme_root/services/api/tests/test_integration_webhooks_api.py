"""An integration's events over the in-process app: the route hands the body
and its headers to the integration, which checks its signature and reads
it; the event is queued for the router named with what served it, the
integration's word and never the body's. A delivery that does not check
out queues nothing."""

import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from api_support import build_container, client_over

from acme.infra.queues import Queues
from acme.integrations.events.twin import SIGNATURE_HEADER, IntegrationTwinImpl, sign
from acme.integrations.identity.twin import IdentityProviderTwinImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import absent_model_providers
from acme.om.base import utcnow
from acme.om.intake.types.event import FeedbackEvent
from acme.services.api.container import AppContainer

ROUTE = "/webhooks/integrations/forge"
ORG = UUID("01a0eba7-0000-7000-8000-000000000001")


@pytest.fixture
def forge() -> IntegrationTwinImpl:
    return IntegrationTwinImpl("forge")


@pytest.fixture
def container(tmp_path: Path, forge: IntegrationTwinImpl) -> AppContainer:
    return build_container(
        tmp_path,
        integrations=IntegrationsOverImpl(
            IdentityProviderTwinImpl(), absent_model_providers(), {"forge": forge}
        ),
    )


async def queued(container: AppContainer) -> list[dict[str, object]]:
    queues = container.infra.get_queues()
    messages = await queues.receive(Queues.WEBHOOKS, 10, timedelta(0), timedelta(seconds=30))
    for message in messages:
        await queues.delete(Queues.WEBHOOKS, message.receipt)
    return [json.loads(message.body) for message in messages]


def a_check(forge: IntegrationTwinImpl) -> tuple[bytes, dict[str, str]]:
    return forge.deliver(
        str(ORG),
        utcnow(),
        arrival="check",
        author_kind="bot",
        branch="agent/fix",
        check="failed",
        text="tests/test_totals.py FAILED",
    )


async def test_a_twins_event_is_queued_once_and_named_the_twins(
    container: AppContainer, forge: IntegrationTwinImpl
) -> None:
    payload, headers = a_check(forge)
    async with client_over(container) as client:
        for _ in range(2):
            answered = await client.post(ROUTE, content=payload, headers=headers)
            assert answered.status_code == 200, answered.text
    first, again = await queued(container)
    assert first == again and first["provider"] == "feedback"
    delivery = first["delivery"]
    assert isinstance(delivery, dict) and UUID(delivery["org_id"]) == ORG
    event = FeedbackEvent.model_validate(delivery["event"])
    assert first["idempotency_key"] == str(event.id)
    assert (event.integration, event.provenance.value) == ("forge", "twin")


async def test_a_body_that_claims_to_be_real_is_queued_as_the_twins(
    container: AppContainer, forge: IntegrationTwinImpl
) -> None:
    payload, _ = a_check(forge)
    claimed = json.dumps({**json.loads(payload), "provenance": "real"}).encode()
    headers = {SIGNATURE_HEADER: sign(claimed, "twin-integration-secret", utcnow())}
    async with client_over(container) as client:
        answered = await client.post(ROUTE, content=claimed, headers=headers)
    assert answered.status_code == 200, answered.text
    [sent] = await queued(container)
    delivery = sent["delivery"]
    assert isinstance(delivery, dict)
    assert FeedbackEvent.model_validate(delivery["event"]).provenance.value == "twin"


async def test_a_delivery_that_does_not_check_out_queues_nothing(
    container: AppContainer, forge: IntegrationTwinImpl
) -> None:
    payload, headers = a_check(forge)
    no_org = forge.deliver("not-an-org", utcnow(), arrival="comment", author_kind="person")
    no_event = forge.deliver(str(ORG), utcnow(), arrival="a dance", author_kind="person")
    cases = (
        (payload, {}),
        (payload.replace(b"FAILED", b"PASSED"), headers),
        no_org,
        no_event,
    )
    async with client_over(container) as client:
        for content, sent_headers in cases:
            refused = await client.post(ROUTE, content=content, headers=sent_headers)
            assert refused.status_code == 400, refused.text
            assert refused.json()["error"]["code"] == "webhook_signature_invalid"
        absent = await client.post("/webhooks/integrations/chat", content=payload, headers=headers)
        assert absent.status_code == 503, absent.text
    depth = await container.infra.get_queues().depth(Queues.WEBHOOKS)
    assert (depth.visible, depth.in_flight) == (0, 0)


async def test_the_route_takes_no_credential(
    client: httpx.AsyncClient, forge: IntegrationTwinImpl
) -> None:
    payload, headers = a_check(forge)
    answered = await client.post(ROUTE, content=payload, headers=headers)
    assert answered.status_code == 200, answered.text
