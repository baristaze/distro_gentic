"""The owner's stations file: limits the platform cannot raise, an
operation the station does not accept refused, and the declared device
access as the host's service configuration, one line per device."""

from pathlib import Path

import pytest

from acme.apps.station_daemon import stations
from acme.apps.station_daemon.config import BadSetting
from acme.om.base import new_id

FILE = """
[[stations]]
id = "{id}"
name = "station-1"
adapter = "twin"
devices = ["/dev/station0", "/dev/station0-power"]
operations = ["apply", "measure"]
controlled_stop = "hold"

[stations.limits.speed]
min = 0.0
max = 1.0

[stations.limits.firmware]
allowed = ["1.2.0"]
"""


def loaded(tmp_path: Path, text: str = FILE) -> stations.Station:
    path = tmp_path / "stations.toml"
    station_id = new_id()
    path.write_text(text.format(id=station_id))
    return stations.load(path)[station_id]


def test_a_command_past_a_limit_is_refused_and_one_within_runs(tmp_path: Path) -> None:
    station = loaded(tmp_path)
    assert stations.refusal(station, "apply", {"speed": 0.5, "firmware": "1.2.0"}) is None
    for parameters in (
        {"speed": 1.5},
        {"speed": -0.1},
        {"speed": "fast"},
        {"speed": True},
        {"speed": float("nan")},
        {"firmware": "9.9.9"},
    ):
        found = stations.refusal(station, "apply", parameters)
        assert found is not None and found[0] == stations.LIMIT, parameters
    unknown = stations.refusal(station, "reflash", {})
    assert unknown is not None and unknown[0] == stations.UNKNOWN_OPERATION


def test_nothing_a_command_carries_raises_a_limit(tmp_path: Path) -> None:
    station = loaded(tmp_path)
    raising = {
        "speed": 9.0,
        "limits": {"speed": {"max": 100}},
        "max": 100,
        "override": True,
    }
    found = stations.refusal(station, "apply", raising)
    assert found is not None and found[0] == stations.LIMIT
    assert station.limits["speed"].high == 1.0
    with pytest.raises(TypeError):
        station.limits["speed"] = stations.Limit(high=100.0)  # type: ignore[index]


def test_a_daemon_with_no_stations_file_or_a_wrong_one_does_not_start(tmp_path: Path) -> None:
    with pytest.raises(BadSetting):
        stations.load(tmp_path / "missing.toml")
    for wrong in (
        FILE.replace('adapter = "twin"', 'adapter = "serial"'),
        FILE.replace("min = 0.0", "min = 2.0"),
        FILE.replace('"/dev/station0"', '"/etc/passwd"'),
        FILE + "\nunknown = 1\n",
    ):
        with pytest.raises(BadSetting):
            loaded(tmp_path, wrong)


def test_the_declared_device_access_is_the_service_configuration_line_by_line(
    tmp_path: Path,
) -> None:
    station = loaded(tmp_path)
    config = stations.service_config({station.id: station}).splitlines()
    assert "DevicePolicy=closed" in config
    assert [line for line in config if line.startswith("DeviceAllow=")] == [
        "DeviceAllow=/dev/station0 rw",
        "DeviceAllow=/dev/station0-power rw",
    ]
