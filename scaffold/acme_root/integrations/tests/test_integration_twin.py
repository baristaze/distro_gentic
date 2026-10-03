"""An integration's twin names its provenance on every record it writes, and
the configured root refuses it anywhere but a local environment: what it
signs, what it verifies, and what it records say `twin`, whatever a
delivery claims. The forge's twin holds each owner's repositories by an
installation of that owner's own, and refuses a write through any other."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from acme.integrations.events import INTEGRATIONS, IntegrationAbsentImpl
from acme.integrations.events.twin import (
    SIGNATURE_HEADER,
    IntegrationTwinImpl,
    sign,
    twin_installation,
)
from acme.integrations.exceptions import (
    DeliveryRefused,
    ProviderRefused,
    ProviderUnavailable,
    UnsafeIntegration,
)
from acme.integrations.impl.configured import IntegrationsConfiguredImpl
from acme.integrations.settings import IntegrationsSettings

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def settings(**values: object) -> IntegrationsSettings:
    return IntegrationsSettings.model_validate({"_env_file": None, **values})


def comment(twin: IntegrationTwinImpl, **changes: object) -> tuple[bytes, dict[str, str]]:
    fields: dict[str, object] = {
        "arrival": "comment",
        "author_kind": "person",
        "pull_request": "acme/app#7",
        "text": "Why is the build slow?",
        **changes,
    }
    return twin.deliver("org-1", NOW, **fields)


def test_every_record_the_twin_writes_names_it() -> None:
    twin = IntegrationTwinImpl("forge")
    payload, headers = comment(twin)
    body = json.loads(payload)
    assert body["provenance"] == "twin"
    assert body["delivery_id"].startswith("twin_") and body["author_id"].startswith("twin_")
    event = twin.verify_delivery(payload, headers, NOW)
    assert (event.delivery_id, event.installation) == (body["delivery_id"], "org-1")
    assert twin.provenance == "twin"


async def test_a_message_the_platform_posts_is_recorded_as_the_twins() -> None:
    twin = IntegrationTwinImpl("chat")
    posted = await twin.post("ann", "The session waits for your approval: /v1/x")
    assert posted.provenance == "twin" and posted.id.startswith("twin_")
    assert twin.posted == [posted]


async def test_each_owners_repositories_are_written_through_an_installation_of_its_own() -> None:
    twin = IntegrationTwinImpl("forge")
    ajax, brio = "https://example.test/ajax/first.git", "https://example.test/Brio/first.git"
    assert await twin.installation_of(ajax) == twin_installation("ajax")
    assert await twin.installation_of("ajax/first#3") == twin_installation("ajax")
    assert (
        await twin.installation_of(brio) == twin_installation("brio") != twin_installation("ajax")
    )

    await twin.push(ajax, "refs/heads/x", "abc", b"", installation=twin_installation("ajax"))
    opened = await twin.open_pull_request(
        ajax, "x", "main", "T", "B", installation=twin_installation("ajax")
    )
    assert await twin.installation_of(opened.id) == twin_installation("ajax")
    await twin.post(opened.id, "Fixed.", installation=twin_installation("ajax"))
    for installation in (twin_installation("brio"), None):
        with pytest.raises(ProviderRefused):
            await twin.post("ajax/first#3", "Fixed.", installation=installation)
    with pytest.raises(ProviderRefused):
        await twin.push(brio, "refs/heads/x", "abc", b"", installation=twin_installation("ajax"))
    with pytest.raises(ProviderRefused):
        await twin.installation_of("twin_pull_request_999999")
    assert twin.refs == {(ajax, "refs/heads/x"): "abc"} and len(twin.posted) == 1


def test_a_body_that_claims_to_be_real_is_still_the_twins() -> None:
    twin = IntegrationTwinImpl("forge")
    body = {
        "delivery_id": "d-1",
        "installation": "org-1",
        "arrival": "check",
        "author_kind": "bot",
        "author_id": "ci",
        "author_name": "ci",
        "check": "failed",
        "occurred_at": NOW.isoformat(),
        "provenance": "real",
    }
    payload = json.dumps(body).encode()
    twin.verify_delivery(
        payload, {SIGNATURE_HEADER: sign(payload, "twin-integration-secret", NOW)}, NOW
    )
    assert twin.provenance == "twin"


@pytest.mark.parametrize(
    "tamper",
    ["no_header", "other_secret", "changed_body", "old", "not_an_event"],
)
def test_a_delivery_that_does_not_check_out_is_refused(tamper: str) -> None:
    twin = IntegrationTwinImpl("forge")
    payload, headers = comment(twin)
    if tamper == "no_header":
        headers = {}
    elif tamper == "other_secret":
        headers = {SIGNATURE_HEADER: sign(payload, "another", NOW)}
    elif tamper == "changed_body":
        payload = payload.replace(b"slow", b"fast")
    elif tamper == "old":
        headers = {
            SIGNATURE_HEADER: sign(payload, "twin-integration-secret", NOW - timedelta(minutes=6))
        }
    else:
        payload = b'{"delivery_id": "d"}'
        headers = {SIGNATURE_HEADER: sign(payload, "twin-integration-secret", NOW)}
    with pytest.raises(DeliveryRefused):
        twin.verify_delivery(payload, headers, NOW)


@pytest.mark.parametrize("environment", ["dev", "staging", "production"])
def test_the_twin_refuses_to_start_outside_local(environment: str) -> None:
    with pytest.raises(UnsafeIntegration, match="ACME_INTEGRATIONS=twin"):
        IntegrationsConfiguredImpl(settings(integrations="twin"), environment, True)


@pytest.mark.parametrize("environment", ["dev", "staging", "production"])
@pytest.mark.parametrize(
    ("setting", "values"),
    [
        ("ACME_FORGE_TWIN_USERNAME", {"forge_twin_username": "forge"}),
        ("ACME_FORGE_TWIN_PASSWORD", {"forge_twin_password": "forge-writes"}),
    ],
)
def test_the_forge_twins_credential_is_refused_outside_local(
    environment: str, setting: str, values: dict[str, object]
) -> None:
    with pytest.raises(UnsafeIntegration, match=setting):
        IntegrationsConfiguredImpl(settings(**values), environment, True)


@pytest.mark.parametrize("environment", ["local", "test"])
def test_the_twin_serves_every_integration_locally(environment: str) -> None:
    root = IntegrationsConfiguredImpl(settings(integrations="twin"), environment, False)
    for name in INTEGRATIONS:
        integration = root.get_integration(name)
        assert isinstance(integration, IntegrationTwinImpl) and integration.provenance == "twin"
    assert "forge=twin" in root.describe()


async def test_an_integration_this_process_lacks_refuses_every_call() -> None:
    root = IntegrationsConfiguredImpl(settings(), "staging", True)
    absent = root.get_integration("forge")
    assert isinstance(absent, IntegrationAbsentImpl)
    with pytest.raises(ProviderUnavailable):
        absent.verify_delivery(b"{}", {}, NOW)
    with pytest.raises(ProviderUnavailable):
        await absent.post("ann", "hello")
