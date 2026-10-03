"""The forge's and the chat's real clients behind the ingress, over the
systems' recorded deliveries and a transport that reaches no network: a
tenant connects an installation with the grant the system confirms, a
delivery signed with the App's secret is queued for that tenant and no
other, one signed with any other secret is refused and queues nothing, and
the system's check of the address is answered and queues nothing."""

import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from api_support import build_container, client_over, seed_request, sign_in_as
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from acme.infra.queues import Queues
from acme.integrations.events import github_wire, slack_wire
from acme.integrations.events.github import GitHubImpl
from acme.integrations.events.slack import SlackImpl
from acme.integrations.identity.twin import IdentityProviderTwinImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import absent_model_providers
from acme.om.base import utcnow
from acme.om.intake.types.event import FeedbackEvent
from acme.services.api.container import AppContainer

FIXTURES = Path(__file__).parents[3] / "integrations" / "tests" / "fixtures"
SECRET = "the-apps-webhook-secret"


def github_answers(request: httpx.Request) -> httpx.Response:
    """GitHub's side of a grant: the person's code, and the installations
    that person may reach (71001 and 71009)."""
    if request.url.path == "/login/oauth/access_token":
        return httpx.Response(200, json={"access_token": "the-persons-token"})
    if request.url.path == "/user/installations":
        return httpx.Response(
            200, content=(FIXTURES / "github/user_installations.json").read_bytes()
        )
    raise AssertionError(request.url)


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    forge = GitHubImpl(
        http=httpx.AsyncClient(transport=httpx.MockTransport(github_answers)),
        app_id="9100",
        private_key=rsa.generate_private_key(public_exponent=65537, key_size=2048),
        webhook_secret=SecretStr(SECRET),
        client_id="Iv1.client",
        client_secret=SecretStr("the-oauth-client-secret"),
        account="acme-app[bot]",
    )
    chat = SlackImpl(
        http=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
        bot_token=SecretStr("the-bot-token"),
        signing_secret=SecretStr(SECRET),
        client_id="1111.2222",
        client_secret=SecretStr("the-oauth-client-secret"),
        account="U0PLATFRM",
    )
    return build_container(
        tmp_path,
        integrations=IntegrationsOverImpl(
            IdentityProviderTwinImpl(), absent_model_providers(), {"forge": forge, "chat": chat}
        ),
    )


async def queued(container: AppContainer) -> list[dict[str, object]]:
    queues = container.infra.get_queues()
    messages = await queues.receive(Queues.WEBHOOKS, 10, timedelta(0), timedelta(seconds=30))
    for message in messages:
        await queues.delete(Queues.WEBHOOKS, message.receipt)
    return [json.loads(message.body) for message in messages]


async def connected(
    container: AppContainer, client: httpx.AsyncClient, name: str, installation: str
) -> UUID:
    """A tenant of its own that connected `installation` of the forge with
    the setup redirect's query GitHub handed its owner."""
    email = f"owner@{name}.test"
    _, org = await container.managers.tenancy.bootstrap(
        seed_request(), name.title(), name, email, name.title()
    )
    headers = await sign_in_as(client, email, org.id)
    answered = await client.post(
        "/v1/integrations/forge/installations",
        headers=headers,
        json={"grant": f"installation_id={installation}&code=a1b2c3"},
    )
    assert answered.status_code == 201, answered.text
    return org.id


def a_comment(secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    """GitHub's recorded comment on a pull request of installation 71001."""
    payload = (FIXTURES / "github/issue_comment.json").read_bytes()
    return payload, {
        github_wire.EVENT_HEADER: "issue_comment",
        github_wire.SIGNATURE_HEADER: github_wire.sign(payload, secret),
    }


async def test_a_signed_delivery_is_queued_for_the_tenant_that_connected_its_installation(
    container: AppContainer,
) -> None:
    payload, headers = a_comment()
    async with client_over(container) as client:
        ajax = await connected(container, client, "ajax", "71001")
        await connected(container, client, "bravo", "71009")
        answered = await client.post(
            "/webhooks/integrations/forge", content=payload, headers=headers
        )
    assert answered.status_code == 200, answered.text
    (only,) = await queued(container)
    delivery = only["delivery"]
    assert isinstance(delivery, dict) and UUID(delivery["org_id"]) == ajax
    event = FeedbackEvent.model_validate(delivery["event"])
    assert (event.integration, event.provenance.value) == ("forge", "real")
    assert (event.author.external_id, event.names.pull_request) == ("583231", "octo-org/widgets#12")


async def test_a_delivery_signed_with_the_wrong_secret_is_refused_and_queues_nothing(
    container: AppContainer,
) -> None:
    payload, headers = a_comment(secret="a-forged-secret")
    async with client_over(container) as client:
        await connected(container, client, "ajax", "71001")
        answered = await client.post(
            "/webhooks/integrations/forge", content=payload, headers=headers
        )
    assert answered.status_code == 400
    assert answered.json()["error"]["code"] == "webhook_signature_invalid"
    assert await queued(container) == []


async def test_the_chats_address_check_is_answered_with_its_challenge_and_queues_nothing(
    container: AppContainer,
) -> None:
    payload = (FIXTURES / "slack/url_verification.json").read_bytes()
    headers = slack_wire.sign(payload, SECRET, utcnow())
    async with client_over(container) as client:
        answered = await client.post(
            "/webhooks/integrations/chat", content=payload, headers=headers
        )
    assert answered.status_code == 200, answered.text
    assert answered.json()["challenge"] == json.loads(payload)["challenge"]
    assert await queued(container) == []
