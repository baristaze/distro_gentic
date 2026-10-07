"""Where a host finds the platform, its own credential, and its owner's
ceilings. Everything comes from the environment or from files on the host.
What every claimant reads, the host reads as the claimant kit does, under
the prefix `ACME` and the kind `host`: `ACME_API_URL`, `ACME_HOST_HOME`
(default `~/.config/acme-host`), which holds the host's `credential.json`
and the owner's `ceilings.toml`, `ACME_HOST_NAME`, the name it enrolls
under, and `ACME_ENROLLMENT_TOKEN`, read once at its first start. Its own
are `ACME_HOST_WORKSPACE_USER`, the dedicated user a bare-directory
workspace runs as, the image a container workspace runs, and how long a
pull of it may take. Nothing the platform answers changes any of them."""

import os
from dataclasses import dataclass
from pathlib import Path

from acme.client.claimant.credential import BadSetting
from acme.client.claimant.settings import ClaimantSettings, claimant_env

ENV_PREFIX = "ACME"
KIND = "host"
DEFAULT_IMAGE = "python:3.14"
"""The image a container workspace runs unless its owner names another: the
engine's own default, which holds Python and `git`."""
CEILINGS_FILE = "ceilings.toml"
SECRETS_FILE = "secrets"
RECORDS_FOLDER = "records"


@dataclass(frozen=True, kw_only=True)
class Settings(ClaimantSettings):
    workspace_user: str | None
    workspace_image: str = DEFAULT_IMAGE
    pull_timeout_seconds: float = 900.0
    max_clock_skew_seconds: float = 60.0

    @property
    def ceilings_path(self) -> Path:
        return self.home / CEILINGS_FILE

    @property
    def secrets_path(self) -> Path:
        """The host's own secret store, owner-only, keyed by tenant first:
        `org/<org_id>/<name>=value` lines."""
        return self.home / SECRETS_FILE

    @property
    def records_path(self) -> Path:
        """Where its transport records how each command ended."""
        return self.home / RECORDS_FOLDER


def _seconds(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if not value > 0:
        raise BadSetting(f"{name} is a number of seconds above zero, not {raw!r}")
    return value


def settings_from_env() -> Settings:
    return Settings(
        **claimant_env(ENV_PREFIX, KIND),
        workspace_user=os.environ.get("ACME_HOST_WORKSPACE_USER") or None,
        workspace_image=os.environ.get("ACME_HOST_WORKSPACE_IMAGE") or DEFAULT_IMAGE,
        pull_timeout_seconds=_seconds("ACME_HOST_PULL_TIMEOUT_SECONDS", 900.0),
    )
