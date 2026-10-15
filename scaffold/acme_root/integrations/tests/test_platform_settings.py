"""The platform's integrations settings are a section of their own:
`IntegrationsSettings` takes them in and declares none of them itself, and
each secret of the section reads empty or "off" as unset."""

import inspect

import pytest

from acme.integrations.platform_settings import PlatformIntegrationsSettings
from acme.integrations.settings import IntegrationsSettings

SECRETS = sorted(
    name for name, field in PlatformIntegrationsSettings.model_fields.items() if not field.repr
)


def test_the_integrations_settings_declare_none_of_the_section() -> None:
    section = set(PlatformIntegrationsSettings.model_fields)
    assert section <= set(IntegrationsSettings.model_fields)
    assert not section & set(inspect.get_annotations(IntegrationsSettings))


def test_the_section_holds_the_forge_and_chat_secrets() -> None:
    assert SECRETS == [
        "forge_twin_password",
        "github_client_secret",
        "github_private_key",
        "github_webhook_secret",
        "slack_bot_token",
        "slack_client_secret",
        "slack_signing_secret",
    ]


@pytest.mark.parametrize("name", SECRETS)
@pytest.mark.parametrize("value", ["", "off", " OFF "])
def test_a_secret_off_is_unset(name: str, value: str) -> None:
    settings = IntegrationsSettings.model_validate({"_env_file": None, name: value})
    assert getattr(settings, name) is None


@pytest.mark.parametrize("name", SECRETS)
def test_a_secret_set_is_kept(name: str) -> None:
    settings = IntegrationsSettings.model_validate({"_env_file": None, name: "s3cret"})
    assert getattr(settings, name).get_secret_value() == "s3cret"


def test_the_section_reads_its_variables_under_the_process_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACME_GITHUB_APP_ID", "42")
    monkeypatch.setenv("ACME_SLACK_BOT_TOKEN", "xoxb-set")
    settings = IntegrationsSettings.model_validate({"_env_file": None})
    assert settings.github_app_id == "42"
    assert settings.slack_bot_token is not None
    assert settings.slack_bot_token.get_secret_value() == "xoxb-set"
