"""The fence: the highest lease token the daemon has seen for each station,
kept on its disk, so a restart forgets none. Every command is checked
against it. A lower token is refused. A higher one is accepted only once
the station has taken its controlled stop and its baseline is restored,
so nothing a previous holder left running or set carries over to the
next."""

import json
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from acme.apps.station_daemon.config import BadSetting, write_private


class Admission(StrEnum):
    RUN = "run"  # the token is the highest seen
    FENCED = "fenced"  # the token is below the highest seen: refused
    TAKEN = "taken"  # the token is higher: the station was stopped and restored first


class Fence:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._highest: dict[UUID, int] = {}
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError:
            return
        except (OSError, ValueError) as error:
            raise BadSetting(f"the fence cannot be read from {path}: {error}") from None
        if not isinstance(raw, dict):
            raise BadSetting(f"the fence in {path} is not a table of tokens")
        try:
            self._highest = {UUID(key): int(value) for key, value in raw.items()}
        except (TypeError, ValueError) as error:
            raise BadSetting(f"the fence in {path}: {error}") from None

    def highest(self, station_id: UUID) -> int:
        """The highest token seen for the station; 0 before any."""
        return self._highest.get(station_id, 0)

    async def admit(
        self, station_id: UUID, token: int, stop_and_restore: Callable[[], Awaitable[None]]
    ) -> Admission:
        """Whether a command under `token` may run on the station. A higher
        token than any seen is taken only after `stop_and_restore` returns,
        and is kept on the disk before the command runs."""
        seen = self.highest(station_id)
        if token < seen:
            return Admission.FENCED
        if token == seen:
            return Admission.RUN
        await stop_and_restore()
        self._highest[station_id] = token
        write_private(
            self._path,
            json.dumps({str(key): value for key, value in self._highest.items()}) + "\n",
        )
        return Admission.TAKEN
