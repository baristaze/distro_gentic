"""The owner's stations: what each station is, the device access it needs,
the operations it accepts, its baseline and its controlled stop, and its
limits. They are the owner's own numbers, read from `stations.toml` at
startup and held frozen. No call answers with them and no job carries
them, so nothing the platform sends, a policy, an approval, or a command,
can raise one.

Every command is held to its station before it runs (`refusal`): an
operation the station does not accept is refused, and so is a parameter
past one of its limits, or of the wrong kind for it.

```toml
[[stations]]
id = "0192f1a4-6c1e-7a51-9b0c-2f8e5d4c3b2a"   # as the platform named it
name = "station-1"
adapter = "twin"
devices = ["/dev/station0"]                  # the device access it needs
operations = ["apply", "measure"]
controlled_stop = "hold"

[stations.baseline]
speed = 0.0

[stations.limits.speed]
max = 1.0                                    # and `min`

[stations.limits.firmware]
allowed = ["1.2.0"]
```
"""

import math
import posixpath
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import UUID

from acme.apps.station_daemon.config import BadSetting

ADAPTERS = frozenset({"twin"})
"""The adapters this build carries. A station names one; a real device's
adapter is the owner's to add."""

STATION_KEYS = frozenset(
    {
        "id",
        "name",
        "adapter",
        "devices",
        "operations",
        "controlled_stop",
        "baseline",
        "limits",
    }
)


@dataclass(frozen=True)
class Limit:
    """One parameter's bound: a number between `low` and `high`, either end
    open when None, or one of `allowed`."""

    low: float | None = None
    high: float | None = None
    allowed: frozenset[str] | None = None

    def refused(self, value: object) -> str | None:
        """Why `value` is past this limit, or None when it is within it."""
        if self.allowed is not None:
            if not isinstance(value, str) or value not in self.allowed:
                return f"{value!r} is not one of {sorted(self.allowed)}"
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            return f"{value!r} is not a number"
        if not math.isfinite(value):
            return f"{value!r} is not a finite number"
        if self.low is not None and value < self.low:
            return f"{value} is below {self.low}"
        if self.high is not None and value > self.high:
            return f"{value} is above {self.high}"
        return None


@dataclass(frozen=True)
class Station:
    id: UUID
    name: str
    adapter: str
    devices: tuple[str, ...]
    operations: frozenset[str]
    controlled_stop: str
    baseline: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    limits: Mapping[str, Limit] = field(default_factory=lambda: MappingProxyType({}))


def _strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BadSetting(f"stations: {name} is a list of strings")
    return list(value)


def _number(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise BadSetting(f"stations: {name} is a finite number")
    return float(value)


def _limit(name: str, raw: Any) -> Limit:
    if not isinstance(raw, dict) or not raw or set(raw) - {"min", "max", "allowed"}:
        raise BadSetting(f"stations: the limit {name} holds min and max, or allowed")
    if "allowed" in raw:
        if set(raw) != {"allowed"}:
            raise BadSetting(f"stations: the limit {name} is allowed values or a range, not both")
        return Limit(allowed=frozenset(_strings(raw["allowed"], f"{name}.allowed")))
    low, high = _number(raw.get("min"), f"{name}.min"), _number(raw.get("max"), f"{name}.max")
    if low is not None and high is not None and low > high:
        raise BadSetting(f"stations: the limit {name} has min above max")
    return Limit(low=low, high=high)


def _device(path: str) -> str:
    normal = posixpath.normpath(path)
    if not posixpath.isabs(path) or not normal.startswith("/dev/") or "\n" in path:
        raise BadSetting(f"stations: the device {path!r} is not a path under /dev")
    return normal


def _station(raw: Any) -> Station:
    if not isinstance(raw, dict):
        raise BadSetting("stations: each station is a table")
    unknown = set(raw) - STATION_KEYS
    if unknown:
        raise BadSetting(f"stations: unknown {', '.join(sorted(unknown))}")
    try:
        station_id = UUID(str(raw["id"]))
        name = str(raw["name"])
        adapter = str(raw["adapter"])
        stop = str(raw["controlled_stop"])
    except KeyError as missing:
        raise BadSetting(f"stations: a station names its {missing.args[0]}") from None
    except ValueError as error:
        raise BadSetting(f"stations: {error}") from None
    if adapter not in ADAPTERS:
        raise BadSetting(f"stations: {name} names the adapter {adapter}, which this build lacks")
    baseline = raw.get("baseline", {})
    limits = raw.get("limits", {})
    if not isinstance(baseline, dict) or not isinstance(limits, dict):
        raise BadSetting(f"stations: {name}'s baseline and limits are tables")
    return Station(
        id=station_id,
        name=name,
        adapter=adapter,
        devices=tuple(_device(path) for path in _strings(raw.get("devices", []), "devices")),
        operations=frozenset(_strings(raw.get("operations", []), "operations")),
        controlled_stop=stop,
        baseline=MappingProxyType(dict(baseline)),
        limits=MappingProxyType({key: _limit(key, value) for key, value in limits.items()}),
    )


def load(path: Path) -> dict[UUID, Station]:
    """The owner's stations, by id. A daemon with no stations file does not
    start: there is no limit its owner did not write."""
    try:
        raw = tomllib.loads(path.read_text())
    except OSError as error:
        raise BadSetting(f"the owner's stations cannot be read from {path}: {error}") from None
    except tomllib.TOMLDecodeError as error:
        raise BadSetting(f"stations: {error}") from None
    if set(raw) - {"stations"} or not isinstance(raw.get("stations"), list) or not raw["stations"]:
        raise BadSetting(
            "stations: the file holds a [[stations]] table per station, and nothing else"
        )
    stations = [_station(item) for item in raw["stations"]]
    by_id = {station.id: station for station in stations}
    if len(by_id) != len(stations):
        raise BadSetting("stations: two stations share an id")
    return by_id


UNKNOWN_OPERATION = "unknown_operation"
LIMIT = "limit"


def refusal(
    station: Station, operation: str, parameters: Mapping[str, Any]
) -> tuple[str, str] | None:
    """Why the station's guard refuses a command, as a reason and its
    detail, or None when it may run: an operation the station does not
    accept, or a parameter past one of its limits."""
    if operation not in station.operations:
        return UNKNOWN_OPERATION, f"{station.name} does not accept the operation {operation}"
    for name, value in parameters.items():
        limit = station.limits.get(name)
        if limit is None:
            continue
        why = limit.refused(value)
        if why is not None:
            return LIMIT, f"{name}: {why}, past {station.name}'s limit"
    return None


def service_config(stations: Mapping[UUID, Station]) -> str:
    """The piece of the host's service configuration the stations' declared
    device access becomes: a systemd drop-in that closes every device but
    the declared ones, one line per device, under the station that needs
    it, for its owner to review line by line."""
    lines = [
        "# The station daemon's device access: every device is closed but those",
        "# a station declares in stations.toml, one line each.",
        "[Service]",
        "DevicePolicy=closed",
    ]
    for station in sorted(stations.values(), key=lambda s: s.name):
        lines.append(f"# {station.name} ({station.id})")
        lines.extend(f"DeviceAllow={device} rw" for device in station.devices)
    return "\n".join(lines) + "\n"
