"""The reports the platform has not acknowledged yet. A job's report, with
every command its guard refused, is written here, flushed to the disk,
before it is sent, and taken away only once the platform recorded it. So
a refusal is evidence the moment it happens, and a daemon cut off from
the platform, or stopped, loses none: it sends what is here at its next
turn. A report the platform refuses for good is set aside, never
dropped."""

import json
from pathlib import Path
from typing import Any

from acme.apps.station_daemon.config import write_private

REFUSED_SUFFIX = ".refused.json"


class Journal:
    def __init__(self, path: Path) -> None:
        self._path = path

    def keep(self, job_id: str, report: dict[str, Any]) -> None:
        write_private(
            self._path / f"{job_id}.json",
            json.dumps({"job_id": job_id, "report": report}, indent=2) + "\n",
        )

    def pending(self) -> list[tuple[str, dict[str, Any]]]:
        """Each report not yet acknowledged, oldest first, as its job and its
        body."""
        if not self._path.is_dir():
            return []
        kept = sorted(
            (p for p in self._path.glob("*.json") if not p.name.endswith(REFUSED_SUFFIX)),
            key=lambda p: p.stat().st_mtime_ns,
        )
        found: list[tuple[str, dict[str, Any]]] = []
        for path in kept:
            raw = json.loads(path.read_text())
            found.append((str(raw["job_id"]), dict(raw["report"])))
        return found

    def sent(self, job_id: str) -> None:
        (self._path / f"{job_id}.json").unlink(missing_ok=True)

    def set_aside(self, job_id: str) -> None:
        """A report the platform refused for good stays on the disk, apart,
        for the owner to read."""
        held = self._path / f"{job_id}.json"
        if held.exists():
            held.replace(self._path / f"{job_id}{REFUSED_SUFFIX}")
