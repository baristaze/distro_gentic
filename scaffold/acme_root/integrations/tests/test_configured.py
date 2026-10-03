"""The integrations root picks the provider from settings, and refuses the
twin anywhere but a local environment."""

import json
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from acme.integrations.events.github import GitHubImpl
from acme.integrations.events.slack import SlackImpl
from acme.integrations.exceptions import ProviderUnavailable, UnsafeIntegration
from acme.integrations.identity import workos
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.identity.twin import IdentityProviderTwinImpl
from acme.integrations.identity.workos import IdentityProviderWorkOSImpl
from acme.integrations.impl.configured import (
    IntegrationsConfiguredImpl,
    absent_integrations,
)
from acme.integrations.model_providers import reply_of
from acme.integrations.model_providers.anthropic import ModelProviderAnthropicImpl
from acme.integrations.model_providers.calls import Message, ModelCall
from acme.integrations.model_providers.content import TextBlock
from acme.integrations.model_providers.failures import ModelCallFailed
from acme.integrations.model_providers.openai import ModelProviderOpenAIImpl
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import ErrorKind, ProviderName
from acme.integrations.settings import IntegrationsSettings

DEPLOYED = frozenset({"dev", "staging", "production"})


def settings(**values: object) -> IntegrationsSettings:
    return IntegrationsSettings.model_validate({"_env_file": None, **values})


@pytest.mark.parametrize("environment", ["dev", "staging", "production"])
def test_the_twin_is_refused_in_a_deployed_environment(environment: str) -> None:
    with pytest.raises(UnsafeIntegration, match="ACME_IDENTITY_PROVIDER=twin"):
        IntegrationsConfiguredImpl(
            settings(identity_provider="twin"), environment, environment in DEPLOYED
        )


@pytest.mark.parametrize("environment", ["local", "test"])
def test_the_twin_runs_locally(environment: str) -> None:
    root = IntegrationsConfiguredImpl(
        settings(identity_provider="twin"), environment, environment in DEPLOYED
    )
    assert isinstance(root.get_identity_provider(), IdentityProviderTwinImpl)


@pytest.mark.parametrize("key", [None, "", "off", " OFF "])
def test_workos_without_its_key_is_absent(key: str | None) -> None:
    root = IntegrationsConfiguredImpl(
        settings(identity_provider="workos", workos_client_id="client_x", workos_api_key=key),
        "staging",
        True,
    )
    provider = root.get_identity_provider()
    assert isinstance(provider, IdentityProviderAbsentImpl) and not provider.configured
    assert "ACME_WORKOS_API_KEY" in provider.describe()


def test_workos_without_its_client_id_is_absent() -> None:
    root = IntegrationsConfiguredImpl(
        settings(identity_provider="workos", workos_api_key="sk_test"), "local", False
    )
    assert "ACME_WORKOS_CLIENT_ID" in root.get_identity_provider().describe()


def test_workos_with_both_is_the_real_client_and_says_so_without_the_key() -> None:
    root = IntegrationsConfiguredImpl(
        settings(
            identity_provider="workos", workos_client_id="client_x", workos_api_key="sk_secret"
        ),
        "staging",
        True,
    )
    assert isinstance(root.get_identity_provider(), IdentityProviderWorkOSImpl)
    described = " ".join(root.describe())
    assert "client_x" in described and "sk_secret" not in described
    assert "sk_secret" not in repr(settings(identity_provider="workos", workos_api_key="sk_secret"))


async def test_the_settings_key_is_the_exchanges_secret_and_the_management_calls_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.path == "/user_management/authenticate":
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(201, json={"link": "https://setup.example/portal"})

    class OverTheFake(httpx.AsyncClient):
        def __init__(self, **options: Any) -> None:
            super().__init__(**{**options, "transport": httpx.MockTransport(answer)})

    monkeypatch.setattr(workos.httpx, "AsyncClient", OverTheFake)
    root = IntegrationsConfiguredImpl(
        settings(
            identity_provider="workos", workos_client_id="client_app", workos_api_key="sk_app"
        ),
        "staging",
        True,
    )
    await root.start()
    provider = root.get_identity_provider()
    await provider.portal_link(organization_id="org_1", intent="sso", return_url="https://x")
    await root.close()
    check, link = sent
    assert json.loads(check.content)["client_secret"] == "sk_app"
    assert json.loads(check.content)["client_id"] == "client_app"
    assert link.headers["authorization"] == "Bearer sk_app"


def test_no_provider_is_the_default_and_refuses_every_call() -> None:
    root = IntegrationsConfiguredImpl(settings(), "production", True)
    provider = root.get_identity_provider()
    assert not provider.configured
    with pytest.raises(ProviderUnavailable):
        provider.authorization_url(redirect_uri="https://x/cb", state="s", code_challenge="c")


async def test_the_absent_provider_refuses_every_call() -> None:
    absent = IdentityProviderAbsentImpl("closed")
    for call in (
        absent.authenticate_code("c", code_verifier="v"),
        absent.start_device(),
        absent.authenticate_device("d"),
        absent.ensure_organization(external_id="e", name="n"),
        absent.get_organization("o"),
        absent.send_invitation(email="e@x.test", organization_id="o", expires_in_days=1),
        absent.find_pending_invitation(email="e@x.test", organization_id="o"),
        absent.resend_invitation("i"),
        absent.revoke_invitation("i"),
        absent.accepted_invitation(organization_id="o", user_id="u", email="e@x.test"),
        absent.portal_link(organization_id="o", intent="sso", return_url="https://x"),
    ):
        with pytest.raises(ProviderUnavailable, match="closed"):
            await call
    root = absent_integrations()
    await root.start()
    assert root.describe()[0] == root.get_identity_provider().describe()
    assert len(root.describe()) == 1 + len(ProviderName)
    with pytest.raises(ProviderUnavailable, match="closed"):
        absent.verify_delivery(b"{}", "t=1, v1=x")
    await root.close()


CALL = ModelCall(
    model="claude-haiku-4-5",
    messages=(Message(role="user", blocks=(TextBlock(text="hello"),)),),
    max_output_tokens=10,
)


@pytest.mark.parametrize("environment", ["dev", "staging", "production"])
def test_the_scripted_model_provider_is_refused_in_a_deployed_environment(environment: str) -> None:
    with pytest.raises(UnsafeIntegration, match="ACME_MODEL_PROVIDERS=scripted"):
        IntegrationsConfiguredImpl(settings(model_providers="scripted"), environment, True)


def test_the_scripted_model_provider_runs_locally() -> None:
    root = IntegrationsConfiguredImpl(settings(model_providers="scripted"), "local", False)
    for provider in ProviderName:
        twin = root.get_model_providers().get(provider)
        assert isinstance(twin, ModelProviderScriptedImpl) and twin.provider is provider


async def test_live_model_providers_are_the_adapters_and_say_so_without_their_keys() -> None:
    root = IntegrationsConfiguredImpl(
        settings(model_providers="live", anthropic_api_key="sk-ant-secret", openai_api_key="off"),
        "staging",
        True,
    )
    providers = root.get_model_providers()
    assert isinstance(providers.get(ProviderName.ANTHROPIC), ModelProviderAnthropicImpl)
    assert isinstance(providers.get(ProviderName.OPENAI), ModelProviderOpenAIImpl)
    described = " ".join(root.describe())
    assert "a platform key" in described and "no platform key" in described
    assert "sk-ant-secret" not in described
    assert "sk-ant-secret" not in repr(settings(anthropic_api_key="sk-ant-secret"))
    with pytest.raises(ModelCallFailed) as failed:
        await reply_of(providers.get(ProviderName.OPENAI).stream(CALL))
    assert failed.value.kind is ErrorKind.CREDENTIAL
    await root.close()


async def test_no_model_provider_is_the_default_and_fails_every_call_as_a_credential() -> None:
    root = IntegrationsConfiguredImpl(settings(), "production", True)
    for provider in ProviderName:
        with pytest.raises(ModelCallFailed) as failed:
            await reply_of(root.get_model_providers().get(provider).stream(CALL))
        assert failed.value.kind is ErrorKind.CREDENTIAL


def a_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def github_settings(**values: object) -> dict[str, object]:
    return {
        "forge_integration": "github",
        "github_app_id": "9100",
        "github_private_key": a_pem(),
        "github_webhook_secret": "the-webhook-secret",
        "github_client_id": "Iv1.client",
        "github_client_secret": "the-client-secret",
        "github_account": "acme-app[bot]",
        **values,
    }


def slack_settings(**values: object) -> dict[str, object]:
    return {
        "chat_integration": "slack",
        "slack_bot_token": "the-bot-token",
        "slack_signing_secret": "the-signing-secret",
        "slack_client_id": "1111.2222",
        "slack_client_secret": "the-client-secret",
        "slack_account": "U0PLATFRM",
        **values,
    }


@pytest.mark.parametrize("environment", ["dev", "staging", "production"])
@pytest.mark.parametrize("setting", ["forge_integration", "chat_integration"])
def test_a_forge_or_chat_twin_is_refused_in_a_deployed_environment(
    environment: str, setting: str
) -> None:
    with pytest.raises(UnsafeIntegration, match=f"ACME_{setting.upper()}=twin"):
        IntegrationsConfiguredImpl(settings(**{setting: "twin"}), environment, True)


@pytest.mark.parametrize("environment", ["dev", "staging", "production"])
def test_github_and_slack_serve_a_deployed_environment_and_name_no_secret(
    environment: str,
) -> None:
    values = {**github_settings(), **slack_settings()}
    built = IntegrationsConfiguredImpl(settings(**values), environment, True)
    assert isinstance(built.get_integration("forge"), GitHubImpl)
    assert isinstance(built.get_integration("chat"), SlackImpl)
    described = " ".join(built.describe())
    assert "forge=github" in described and "chat=slack" in described
    for secret in ("the-webhook-secret", "the-client-secret", "the-bot-token", "PRIVATE KEY"):
        assert secret not in described


@pytest.mark.parametrize(
    ("values", "name", "lacks"),
    [
        (github_settings(github_webhook_secret="off"), "forge", "ACME_GITHUB_WEBHOOK_SECRET"),
        (github_settings(github_account=""), "forge", "ACME_GITHUB_ACCOUNT"),
        (github_settings(github_private_key="not a key"), "forge", "ACME_GITHUB_PRIVATE_KEY"),
        (slack_settings(slack_bot_token=""), "chat", "ACME_SLACK_BOT_TOKEN"),
        (slack_settings(slack_account=""), "chat", "ACME_SLACK_ACCOUNT"),
    ],
)
async def test_a_client_without_its_settings_is_absent_and_names_what_it_lacks(
    values: dict[str, object], name: str, lacks: str
) -> None:
    built = IntegrationsConfiguredImpl(settings(**values), "production", True)
    integration = built.get_integration(name)
    assert lacks in integration.describe()
    with pytest.raises(ProviderUnavailable, match=lacks):
        await integration.post("somewhere", "text")


def test_each_integration_follows_integrations_unless_its_own_setting_says() -> None:
    built = IntegrationsConfiguredImpl(
        settings(integrations="twin", forge_integration="none"), "local", False
    )
    assert built.get_integration("forge").describe() == "forge=none"
    assert built.get_integration("chat").provenance == "twin"
