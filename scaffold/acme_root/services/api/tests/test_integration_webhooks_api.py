"""An integration's events over the in-process app: the route hands the body
and its headers to the integration, which checks its signature and reads
it; the event is queued for the router named with what served it, the
integration's word and never the body's, under the tenant that connected
the installation it names. A delivery that does not check out, or that
names an installation no tenant connected, queues nothing."""

import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from api_support import add_member, build_container, client_over, seed_request, sign_in_as

from acme.infra.queues import Queues
from acme.integrations.events.twin import SIGNATURE_HEADER, IntegrationTwinImpl, sign
from acme.integrations.identity.twin import IdentityProviderTwinImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import absent_model_providers
from acme.om.base import utcnow
from acme.om.context import Role
from acme.om.intake.types.event import FeedbackEvent
from acme.services.api.container import AppContainer

ROUTE = "/webhooks/integrations/forge"
CONNECT = "/v1/integrations/forge/installations"
INSTALLATION = "71001"
"""The forge's own id for Ajax's installation of the platform."""


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


async def tenant(
    container: AppContainer, client: httpx.AsyncClient, name: str
) -> tuple[UUID, dict[str, str]]:
    """A tenant of its own, and its owner signed in on it, in person."""
    email = f"owner@{name}.test"
    _, org = await container.managers.tenancy.bootstrap(
        seed_request(), name.title(), name, email, name.title()
    )
    return org.id, await sign_in_as(client, email, org.id)


async def connect(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    forge: IntegrationTwinImpl,
    installation: str,
) -> httpx.Response:
    """The tenant connects the installation with the grant the forge handed
    the person who installed the platform there."""
    return await client.post(
        CONNECT, headers=headers, json={"grant": forge.grant(installation, utcnow())}
    )


@pytest.fixture
async def ajax(container: AppContainer, forge: IntegrationTwinImpl) -> UUID:
    """A tenant that connected INSTALLATION."""
    async with client_over(container) as client:
        org_id, headers = await tenant(container, client, "ajax")
        connected = await connect(client, headers, forge, INSTALLATION)
        assert connected.status_code == 201, connected.text
    return org_id


def a_check(
    forge: IntegrationTwinImpl, installation: str = INSTALLATION
) -> tuple[bytes, dict[str, str]]:
    return forge.deliver(
        installation,
        utcnow(),
        arrival="check",
        author_kind="bot",
        branch="agent/fix",
        check="failed",
        text="tests/test_totals.py FAILED",
    )


async def test_a_twins_event_is_queued_once_and_named_the_twins(
    container: AppContainer, forge: IntegrationTwinImpl, ajax: UUID
) -> None:
    payload, headers = a_check(forge)
    async with client_over(container) as client:
        for _ in range(2):
            answered = await client.post(ROUTE, content=payload, headers=headers)
            assert answered.status_code == 200, answered.text
    first, again = await queued(container)
    assert first == again and first["provider"] == "feedback"
    delivery = first["delivery"]
    assert isinstance(delivery, dict) and UUID(delivery["org_id"]) == ajax
    event = FeedbackEvent.model_validate(delivery["event"])
    assert first["idempotency_key"] == str(event.id)
    assert (event.integration, event.provenance.value) == ("forge", "twin")


async def test_a_body_that_claims_to_be_real_is_queued_as_the_twins(
    container: AppContainer, forge: IntegrationTwinImpl, ajax: UUID
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
    container: AppContainer, forge: IntegrationTwinImpl, ajax: UUID
) -> None:
    payload, headers = a_check(forge)
    no_event = forge.deliver(INSTALLATION, utcnow(), arrival="a dance", author_kind="person")
    cases = (
        (payload, {}),
        (payload.replace(b"FAILED", b"PASSED"), headers),
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
    client: httpx.AsyncClient, forge: IntegrationTwinImpl, ajax: UUID
) -> None:
    payload, headers = a_check(forge)
    answered = await client.post(ROUTE, content=payload, headers=headers)
    assert answered.status_code == 200, answered.text


async def test_a_delivery_reaches_the_tenant_that_connected_its_installation_alone(
    container: AppContainer, forge: IntegrationTwinImpl, ajax: UUID
) -> None:
    async with client_over(container) as client:
        bravo, headers = await tenant(container, client, "bravo")
        connected = await connect(client, headers, forge, "72002")
        assert connected.status_code == 201, connected.text
        for installation in (INSTALLATION, "72002"):
            payload, signed = a_check(forge, installation)
            answered = await client.post(ROUTE, content=payload, headers=signed)
            assert answered.status_code == 200, answered.text
    to_ajax, to_bravo = await queued(container)
    assert [UUID(sent["delivery"]["org_id"]) for sent in (to_ajax, to_bravo)] == [ajax, bravo]  # type: ignore[index]


async def test_a_delivery_naming_no_connected_installation_or_an_org_id_queues_nothing(
    container: AppContainer, forge: IntegrationTwinImpl, ajax: UUID
) -> None:
    """An installation nobody connected, and the org id of a tenant that
    connected one, each name no tenant: the org's id is the platform's,
    never a system's installation."""
    async with client_over(container) as client:
        for installation in ("79999", str(ajax)):
            payload, signed = a_check(forge, installation)
            refused = await client.post(ROUTE, content=payload, headers=signed)
            assert refused.status_code == 400, refused.text
            assert "no installation a tenant connected" in refused.json()["error"]["message"]
    depth = await container.infra.get_queues().depth(Queues.WEBHOOKS)
    assert (depth.visible, depth.in_flight) == (0, 0)


async def test_an_installation_is_connected_by_one_tenant_with_the_systems_grant_in_person(
    container: AppContainer, forge: IntegrationTwinImpl, ajax: UUID
) -> None:
    """Another tenant cannot take the installation over, a grant the system
    did not sign connects nothing, and only a person who manages the
    tenant's members connects one."""
    async with client_over(container) as client:
        bravo, headers = await tenant(container, client, "bravo")
        taken = await connect(client, headers, forge, INSTALLATION)
        assert taken.status_code == 409, taken.text
        forged = IntegrationTwinImpl("forge", secret="not-the-forges").grant("73003", utcnow())
        unsigned = await client.post(CONNECT, headers=headers, json={"grant": forged})
        assert unsigned.status_code == 422, unsigned.text
        # The refused grant connected nothing: a delivery through it names no tenant.
        payload, signed = a_check(forge, "73003")
        assert (await client.post(ROUTE, content=payload, headers=signed)).status_code == 400
        await add_member(container, bravo, "member@bravo.test", Role.MEMBER)
        member = await sign_in_as(client, "member@bravo.test", bravo)
        refused = await connect(client, member, forge, "73003")
        assert refused.status_code == 403, refused.text
        again = await connect(client, headers, forge, "73003")
        assert again.status_code == 201, again.text
        payload, signed = a_check(forge, INSTALLATION)
        assert (await client.post(ROUTE, content=payload, headers=signed)).status_code == 200
    (sent,) = await queued(container)
    assert UUID(sent["delivery"]["org_id"]) == ajax  # type: ignore[index]
