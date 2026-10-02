"""Where a host finds the platform, its own credential, and its owner's
ceilings. Everything comes from the environment or from files on the host:
`ACME_API_URL`, `ACME_HOST_HOME` (default `~/.config/acme-host`), which
holds the host's `credential.json` and the owner's `ceilings.toml`,
`ACME_HOST_NAME`, the name it enrolls under, `ACME_ENROLLMENT_TOKEN`, read
once at its first start, and `ACME_HOST_WORKSPACE_USER`, the dedicated user
a bare-directory workspace runs as. Nothing the platform answers changes
any of them."""

import json
import os
import socket
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_API_URL = "http://127.0.0.1:8000"
CREDENTIAL_FILE = "credential.json"
CEILINGS_FILE = "ceilings.toml"
SECRETS_FILE = "secrets"
RECORDS_FOLDER = "records"


class BadSetting(ValueError):
    """A setting or a file on the host cannot be used: the host says so and
    does not start."""


@dataclass(frozen=True)
class Settings:
    api_url: str
    home: Path
    name: str
    enrollment_token: str | None
    workspace_user: str | None
    max_clock_skew_seconds: float = 60.0
    beat_seconds: float = 30.0

    @property
    def credential_path(self) -> Path:
        return self.home / CREDENTIAL_FILE

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


def settings_from_env() -> Settings:
    home = os.environ.get("ACME_HOST_HOME")
    return Settings(
        api_url=os.environ.get("ACME_API_URL", DEFAULT_API_URL).rstrip("/"),
        home=Path(home) if home else Path.home() / ".config" / "acme-host",
        name=os.environ.get("ACME_HOST_NAME") or socket.gethostname()[:64] or "host",
        enrollment_token=os.environ.get("ACME_ENROLLMENT_TOKEN") or None,
        workspace_user=os.environ.get("ACME_HOST_WORKSPACE_USER") or None,
    )


@dataclass(frozen=True)
class Credential:
    """The host's own credential, as it was issued: the one secret the
    platform hands it, kept owner-only on its disk."""

    api_url: str
    token: str
    credential_id: str
    host_id: str
    pool_id: str
    issued_at: datetime
    expires_at: datetime

    def due(self, now: datetime) -> bool:
        """Rotated at half its life, so a host that misses a beat or two
        still rotates before it ends."""
        return now >= self.issued_at + (self.expires_at - self.issued_at) / 2

    def ended(self, now: datetime) -> bool:
        return now >= self.expires_at


def load_credential(path: Path) -> Credential | None:
    try:
        raw = json.loads(path.read_text())
        return Credential(
            **{
                **raw,
                "issued_at": datetime.fromisoformat(raw["issued_at"]),
                "expires_at": datetime.fromisoformat(raw["expires_at"]),
            }
        )
    except OSError, ValueError, TypeError, KeyError:
        return None


def save_credential(path: Path, credential: Credential) -> None:
    """Created owner-only, never created readable and locked down after."""
    raw = {
        **asdict(credential),
        "issued_at": credential.issued_at.isoformat(),
        "expires_at": credential.expires_at.isoformat(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(json.dumps(raw, indent=2) + "\n")
        path.chmod(0o600)
    except OSError as error:
        raise BadSetting(f"the credential cannot be kept in {path.parent}: {error}") from None
