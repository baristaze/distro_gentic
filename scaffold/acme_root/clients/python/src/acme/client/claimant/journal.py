"""The journal: a claimant's reports, each kept on its disk before it is
sent, and deleted only once the platform recorded it. So a report the
platform did not answer is sent again, and one it recorded is never sent
twice. An entry is keyed by an id the claimant chooses (the item's, by
default) and holds the item it answers for and the body it sends, which
carries the item's claim token as `claim_token`.

Two kinds of entry wait aside, never sent by a flush. One whose item's
claim lapsed waits for a later claim of its item, and lands under it.
One the platform refused for its shape is kept for a person, and never
sent again. Nothing in the journal is a secret, but it is kept
owner-only, as everything in the claimant's home is."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from acme.client.claimant.credential import BadSetting, write_private

LAPSED_SUFFIX = ".lapsed.json"
REFUSED_SUFFIX = ".refused.json"


@dataclass(frozen=True)
class Entry:
    key: str
    item_id: str
    body: dict[str, Any]

    def under(self, item_id: UUID, claim_token: UUID) -> Entry:
        """The same report under a later claim of its item."""
        return Entry(self.key, str(item_id), {**self.body, "claim_token": str(claim_token)})


class Journal:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def keep(self, entry: Entry) -> None:
        """Written whole or not at all, before it is sent. A lapsed copy of
        the same report goes once this one is kept."""
        write_private(self._path(entry.key), json.dumps(asdict(entry)) + "\n")
        self._path(entry.key, LAPSED_SUFFIX).unlink(missing_ok=True)

    def find(self, key: str) -> Entry | None:
        path = self._path(key)
        return _read(path) if path.exists() else None

    def pending(self) -> list[Entry]:
        """Every report a flush sends, oldest first."""
        return [_read(p) for p in self._paths(".json", (LAPSED_SUFFIX, REFUSED_SUFFIX))]

    def lapsed(self, item_id: UUID) -> Entry | None:
        """The report that waits for a later claim of the item, if one does."""
        for path in self._paths(LAPSED_SUFFIX, ()):
            entry = _read(path)
            if entry.item_id == str(item_id):
                return entry
        return None

    def sent(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
        self._path(key, LAPSED_SUFFIX).unlink(missing_ok=True)

    def lapse(self, key: str) -> None:
        """Its item's claim lapsed: it waits for a later claim of the item."""
        self._aside(key, LAPSED_SUFFIX)

    def set_aside(self, key: str) -> None:
        """The platform refused it for its shape: kept for a person, and
        never sent again."""
        self._aside(key, REFUSED_SUFFIX)

    def _aside(self, key: str, suffix: str) -> None:
        path = self._path(key)
        if path.exists():
            path.replace(self._path(key, suffix))

    def _paths(self, suffix: str, but: tuple[str, ...]) -> list[Path]:
        if not self._directory.exists():
            return []
        paths = [
            p
            for p in self._directory.glob(f"*{suffix}")
            if not p.name.startswith(".") and not p.name.endswith(but)
        ]
        paths.sort(key=lambda p: (p.stat().st_mtime_ns, p.name))
        return paths

    def _path(self, key: str, suffix: str = ".json") -> Path:
        """An entry's file, named by its key read as a UUID, so no key
        names a path outside the journal."""
        return self._directory / f"{UUID(key)}{suffix}"


def _read(path: Path) -> Entry:
    try:
        return Entry(**json.loads(path.read_text()))
    except (OSError, ValueError, TypeError) as error:
        raise BadSetting(f"the journal entry {path} cannot be read: {error}") from None
