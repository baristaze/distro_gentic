"""The platform's API settings, a section of their own that `ApiSettings`
takes in under its prefix and its file: the key a live-read handle is
signed with."""

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ACME_", env_file=".env", extra="ignore")

    # The key a live-read handle is signed with, the same in every API
    # process, so any of them reads a handle another issued: at least 32
    # characters, a process credential injected at start like the TOTP key.
    # No default: a process without it refuses every live read, and says so.
    live_read_key: SecretStr | None = None

    @field_validator("live_read_key")
    @classmethod
    def a_live_read_key_is_long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        """A short key is guessed: a process with one refuses to start."""
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("live_read_key is shorter than 32 characters")
        return value
