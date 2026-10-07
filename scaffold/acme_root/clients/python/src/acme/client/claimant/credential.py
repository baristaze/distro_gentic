"""A claimant's own credential, as the platform issued it: the one secret
it holds of the platform's, kept owner-only on its disk. It is written
whole or not at all, so a claimant stopped mid-write still holds the one
before, and it is rotated at half its life."""

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

CREDENTIAL_FILE = "credential.json"


class BadSetting(ValueError):
    """A setting or a file on the machine cannot be used: the claimant says
    so and does not start."""


def write_private(path: Path, text: str) -> None:
    """Written whole or not at all, owner-only from its first byte: a
    temporary file beside it, created at mode 600, flushed to the disk, then
    moved over it. Never created readable and locked down after."""
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        # A file left by a write under another umask is held to 600 too.
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except OSError as error:
        raise BadSetting(f"{path.name} cannot be kept in {path.parent}: {error}") from None


@dataclass(frozen=True)
class Credential:
    """The claimant's credential, the platform it was issued by, and the
    identity it carries: its claimant and its pool, read off it, never
    named by the claimant."""

    api_url: str
    token: str
    credential_id: str
    claimant_id: str
    pool_id: str
    issued_at: datetime
    expires_at: datetime

    def due(self, now: datetime) -> bool:
        """Rotated at half its life, so a claimant that misses a turn or two
        still rotates before it ends."""
        return now >= self.issued_at + (self.expires_at - self.issued_at) / 2

    def ended(self, now: datetime) -> bool:
        return now >= self.expires_at


def load_credential(path: Path) -> Credential | None:
    """The credential kept at `path`, or None when there is none to use.
    `host_id`, the host's name for its claimant, reads as `claimant_id`."""
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            return None
        if "host_id" in raw:
            raw["claimant_id"] = raw.pop("host_id")
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
    raw = {
        **asdict(credential),
        "issued_at": credential.issued_at.isoformat(),
        "expires_at": credential.expires_at.isoformat(),
    }
    write_private(path, json.dumps(raw, indent=2) + "\n")
