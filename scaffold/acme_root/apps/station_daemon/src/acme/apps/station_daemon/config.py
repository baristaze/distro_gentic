"""Where a daemon finds the platform, its own credential, and its owner's
stations. Everything comes from the environment or from files on the
host: `ACME_API_URL`, `ACME_DAEMON_HOME` (default
`~/.config/acme-station-daemon`), which holds the daemon's
`credential.json`, the owner's `stations.toml`, the fence's `fence.json`,
and the `reports/` not yet acknowledged, and `ACME_DAEMON_CREDENTIAL`, the
first credential its owner issued, read once at its first start. Nothing
the platform answers changes any of them."""

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_API_URL = "http://127.0.0.1:8000"
CREDENTIAL_FILE = "credential.json"
STATIONS_FILE = "stations.toml"
FENCE_FILE = "fence.json"
REPORTS_DIR = "reports"


class BadSetting(ValueError):
    """A setting or a file on the host cannot be used: the daemon says so and
    does not start."""


@dataclass(frozen=True)
class Settings:
    api_url: str
    home: Path
    first_credential: str | None
    idle_seconds: float = 5.0

    @property
    def credential_path(self) -> Path:
        return self.home / CREDENTIAL_FILE

    @property
    def stations_path(self) -> Path:
        return self.home / STATIONS_FILE

    @property
    def fence_path(self) -> Path:
        return self.home / FENCE_FILE

    @property
    def reports_path(self) -> Path:
        return self.home / REPORTS_DIR


def settings_from_env() -> Settings:
    home = os.environ.get("ACME_DAEMON_HOME")
    return Settings(
        api_url=os.environ.get("ACME_API_URL", DEFAULT_API_URL).rstrip("/"),
        home=Path(home) if home else Path.home() / ".config" / "acme-station-daemon",
        first_credential=os.environ.get("ACME_DAEMON_CREDENTIAL") or None,
    )


@dataclass(frozen=True)
class Credential:
    """The daemon's own credential, as it was issued: the one secret the
    platform hands it, kept owner-only on its disk."""

    api_url: str
    token: str
    credential_id: str
    lab_id: str
    issued_at: datetime
    expires_at: datetime

    def due(self, now: datetime) -> bool:
        """Rotated at half its life, so a daemon that misses a turn or two
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


def write_private(path: Path, text: str) -> None:
    """A file created owner-only and replaced whole: written beside its
    place, flushed to the disk, then moved over it, so a crash leaves the
    old one or the new one and never half of either."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staged = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    os.replace(staged, path)


def save_credential(path: Path, credential: Credential) -> None:
    raw = {
        **asdict(credential),
        "issued_at": credential.issued_at.isoformat(),
        "expires_at": credential.expires_at.isoformat(),
    }
    try:
        write_private(path, json.dumps(raw, indent=2) + "\n")
    except OSError as error:
        raise BadSetting(f"the credential cannot be kept in {path.parent}: {error}") from None
