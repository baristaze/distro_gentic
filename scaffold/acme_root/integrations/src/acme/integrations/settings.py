"""The settings the integrations read, mixed into a process's one settings
object; nothing below reads the environment."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from acme.infra.impl.settings import ENV_FILE


class IntegrationsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ACME_", env_file=ENV_FILE, extra="ignore")

    # Which identity provider signs people in: WorkOS, its twin (local only,
    # refused at boot anywhere else), or none, which refuses every sign-in
    # through a provider and is what a process that signs nobody in holds.
    identity_provider: Literal["workos", "twin", "none"] = "none"
    # The Acme App application's client id. Not a secret: it is in every
    # authorization URL a browser sees. Each environment names its own
    # application in its deployment config.
    workos_client_id: str = ""
    # The Acme App application's API key, never the environment's: the
    # exchange's client secret and the management calls' key. A process
    # credential, injected at start from the secret store in a deployed
    # environment and read from the environment locally. Empty or "off"
    # means not set, and WorkOS is then not configured: the process starts,
    # says so, and every sign-in through it answers 503.
    workos_api_key: SecretStr | None = Field(default=None, repr=False)
    workos_base_url: str = "https://api.workos.com"
    workos_timeout_seconds: float = Field(default=10.0, gt=0)

    # The signing secret of the endpoint the provider delivers its events
    # to (`/webhooks/identity`). A process credential, injected at start;
    # empty or "off" leaves the route refusing every delivery. The twin signs
    # with its own and ignores this one.
    workos_webhook_secret: SecretStr | None = Field(default=None, repr=False)

    # Which model providers a process calls: the live adapters, the scripted
    # twin (local only, refused at boot anywhere else), or none, which fails
    # every model call as a missing credential and is what a process that
    # calls no model holds.
    model_providers: Literal["live", "scripted", "none"] = "none"
    # The scripted twin's script: a JSON file of each provider's turns, read
    # once at boot, so a process the twin serves answers what a suite
    # scripted for it. None leaves every script empty.
    model_script: Path | None = None
    # The time the scripted twin waits before each part it streams, so a
    # suite can watch a stream while it is open. Zero streams at once.
    model_script_pace_seconds: float = Field(default=0, ge=0)
    # The platform's own keys, process credentials injected at start. Empty
    # or "off" leaves the provider with no platform key: a call runs only on
    # a credential of its own, and without one fails as `credential`.
    anthropic_api_key: SecretStr | None = Field(default=None, repr=False)
    anthropic_base_url: str = "https://api.anthropic.com"
    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    openai_base_url: str = "https://api.openai.com"
    # The longest a model call waits on the network at one time: to connect,
    # to send, and between two parts of a streamed answer.
    model_timeout_seconds: float = Field(default=120.0, gt=0)

    # What serves the integrations whose events reach a session and through
    # which a person is told what waits on them (`events.INTEGRATIONS`): their
    # twins (local only, refused at boot anywhere else), or none, which
    # refuses every delivery and every post as unavailable.
    integrations: Literal["twin", "none"] = "none"
    # The credential the forge's twin pushes with, for a repository behind
    # basic authentication: a user and a password or token that may write
    # to it. Local only, as the twin is, and refused at boot anywhere else.
    # The password empty or "off" leaves the twin pushing with none.
    forge_twin_username: str = ""
    forge_twin_password: SecretStr | None = Field(default=None, repr=False)
    # What serves the forge and the chat each, where it is not what
    # `integrations` says: the system's client, the twin (local only, refused
    # at boot anywhere else), or none. Unset follows `integrations`.
    forge_integration: Literal["github", "twin", "none"] | None = None
    chat_integration: Literal["slack", "twin", "none"] | None = None

    # The forge as a GitHub App: the App's id; its private key, a PEM, which
    # signs the JWT it trades for each installation's token; the secret its
    # webhook signs each delivery with; its OAuth client, which confirms the
    # person who installed it; and the login of its bot, the platform's own
    # account there (`<slug>[bot]`). The secrets are process credentials,
    # injected at start; empty or "off" leaves one unset, and without any of
    # these the forge is absent.
    github_app_id: str = ""
    github_private_key: SecretStr | None = Field(default=None, repr=False)
    github_webhook_secret: SecretStr | None = Field(default=None, repr=False)
    github_client_id: str = ""
    github_client_secret: SecretStr | None = Field(default=None, repr=False)
    github_account: str = ""
    github_api_url: str = "https://api.github.com"
    github_web_url: str = "https://github.com"
    github_timeout_seconds: float = Field(default=10.0, gt=0)

    # The chat as a Slack app: its bot token, which every post carries; the
    # secret Slack signs each delivery with; its OAuth client, which
    # confirms the workspace a person installed it in; and the user id of
    # its bot, the platform's own account there. As the forge's: secrets
    # injected at start, empty or "off" unset, and without any of these the
    # chat is absent.
    slack_bot_token: SecretStr | None = Field(default=None, repr=False)
    slack_signing_secret: SecretStr | None = Field(default=None, repr=False)
    slack_client_id: str = ""
    slack_client_secret: SecretStr | None = Field(default=None, repr=False)
    slack_account: str = ""
    slack_api_url: str = "https://slack.com/api"
    slack_timeout_seconds: float = Field(default=10.0, gt=0)

    @field_validator(
        "workos_api_key",
        "anthropic_api_key",
        "openai_api_key",
        "forge_twin_password",
        "github_private_key",
        "github_webhook_secret",
        "github_client_secret",
        "slack_bot_token",
        "slack_signing_secret",
        "slack_client_secret",
    )
    @classmethod
    def _key_off_is_none(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or value.get_secret_value().strip().lower() in ("", "off"):
            return None
        return value

    @field_validator("workos_webhook_secret", mode="before")
    @classmethod
    def _secret_off_is_none(cls, value: object) -> object:
        """The cloud secret starts as "off", as the error tracker's DSN does."""
        if isinstance(value, str) and value.strip().lower() in ("", "off"):
            return None
        return value
