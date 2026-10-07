"""Where a claimant finds the platform, its home, the name it enrolls
under, and its enrollment token: the environment, under its prefix and
its kind. With the prefix `ACME` and the kind `host`, they are
`ACME_API_URL`, `ACME_HOST_HOME` (default `~/.config/acme-host`),
`ACME_HOST_NAME` (default the machine's name), and
`ACME_ENROLLMENT_TOKEN`, read once at its first start. The installer
writes the same names into the claimant's settings file. Nothing the
platform answers changes any of them."""

import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acme.client.claimant.credential import CREDENTIAL_FILE

DEFAULT_API_URL = "http://127.0.0.1:8000"
JOURNAL_FOLDER = "journal"


@dataclass(frozen=True, kw_only=True)
class ClaimantSettings:
    api_url: str
    home: Path
    name: str
    enrollment_token: str | None
    beat_seconds: float = 30.0
    """The wait between turns while there is no work."""

    @property
    def credential_path(self) -> Path:
        return self.home / CREDENTIAL_FILE

    @property
    def journal_path(self) -> Path:
        """Where its reports wait until the platform records them."""
        return self.home / JOURNAL_FOLDER

    @classmethod
    def from_env(cls, prefix: str, kind: str) -> ClaimantSettings:
        return cls(**claimant_env(prefix, kind))


def variable(prefix: str, kind: str, setting: str) -> str:
    """A kind's own variable: `ACME_HOST_NAME` for `ACME`, `host`, `NAME`."""
    return f"{prefix}_{kind.upper()}_{setting}"


def claimant_env(
    prefix: str, kind: str, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """The settings every claimant reads, by name, for a kind's own
    settings to add to."""
    env = os.environ if environ is None else environ
    home = env.get(variable(prefix, kind, "HOME"))
    folder = f"{prefix}-{kind}".lower().replace("_", "-")
    return {
        "api_url": env.get(f"{prefix}_API_URL", DEFAULT_API_URL).rstrip("/"),
        "home": Path(home) if home else Path.home() / ".config" / folder,
        "name": env.get(variable(prefix, kind, "NAME")) or socket.gethostname()[:64] or kind,
        "enrollment_token": env.get(f"{prefix}_ENROLLMENT_TOKEN") or None,
    }
