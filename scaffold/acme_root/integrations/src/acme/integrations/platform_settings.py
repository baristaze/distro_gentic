"""The platform's integrations settings, a section of their own that
`IntegrationsSettings` takes in and reads from its file: the scripted
twin's pace, what serves the forge and the chat, and their apps. The
section names the prefix itself, so each of its variables reads as the
process reads it."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformIntegrationsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ACME_", extra="ignore")

    # The time the scripted twin waits before each part it streams, so a
    # suite can watch a stream while it is open. Zero streams at once.
    llm_script_pace_seconds: float = Field(default=0, ge=0)

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
        "forge_twin_password",
        "github_private_key",
        "github_webhook_secret",
        "github_client_secret",
        "slack_bot_token",
        "slack_signing_secret",
        "slack_client_secret",
    )
    @classmethod
    def _platform_key_off_is_none(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or value.get_secret_value().strip().lower() in ("", "off"):
            return None
        return value
