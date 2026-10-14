"""The integrations root picks the forge and the chat from settings: GitHub
and Slack serve a deployed environment, the twin of either is refused there,
and a client without its settings is absent and names what it lacks."""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from acme.integrations.events.github import GitHubImpl
from acme.integrations.events.slack import SlackImpl
from acme.integrations.exceptions import ProviderUnavailable, UnsafeIntegration
from acme.integrations.impl.configured import IntegrationsConfiguredImpl
from acme.integrations.settings import IntegrationsSettings


def settings(**values: object) -> IntegrationsSettings:
    return IntegrationsSettings.model_validate({"_env_file": None, **values})


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
