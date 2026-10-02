"""The fence on the daemon's disk: a token below the highest seen is
refused, a higher one is taken only after the station's controlled stop
and its baseline, and a restart forgets no token."""

from pathlib import Path

import pytest

from acme.apps.station_daemon.config import BadSetting
from acme.apps.station_daemon.fence import Admission, Fence
from acme.om.base import new_id


async def test_a_lower_token_is_refused_and_a_higher_one_stops_and_restores_first(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fence.json"
    fence = Fence(path)
    station = new_id()
    done: list[str] = []

    async def stop_and_restore() -> None:
        done.append("stop and restore")

    assert await fence.admit(station, 2, stop_and_restore) is Admission.TAKEN
    assert done == ["stop and restore"]
    assert await fence.admit(station, 2, stop_and_restore) is Admission.RUN
    assert await fence.admit(station, 1, stop_and_restore) is Admission.FENCED
    assert done == ["stop and restore"]
    # A restart reads the highest from the disk, and still refuses the lower.
    again = Fence(path)
    assert again.highest(station) == 2
    assert await again.admit(station, 1, stop_and_restore) is Admission.FENCED
    assert await again.admit(station, 3, stop_and_restore) is Admission.TAKEN
    assert done == ["stop and restore", "stop and restore"]


async def test_a_token_is_taken_only_once_the_station_stopped(tmp_path: Path) -> None:
    fence = Fence(tmp_path / "fence.json")
    station = new_id()

    async def fails() -> None:
        raise RuntimeError("the station did not stop")

    with pytest.raises(RuntimeError):
        await fence.admit(station, 1, fails)
    assert fence.highest(station) == 0


def test_a_fence_file_that_cannot_be_read_stops_the_daemon(tmp_path: Path) -> None:
    path = tmp_path / "fence.json"
    path.write_text("not json")
    with pytest.raises(BadSetting):
        Fence(path)
