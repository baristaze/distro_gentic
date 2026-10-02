"""A station's adapter: the one way anything reaches the station. A job is
data, operations with their parameters, and the daemon hands each one,
once the guard let it through, to the station's adapter; no code a job
holds runs here. This build carries the twin, a deterministic stand-in
that names itself as one, so every run it serves is a twin's run and
never a real one."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from acme.apps.station_daemon.stations import Station


@dataclass(frozen=True)
class Outcome:
    """What one operation came to: whether it did what it was asked, and
    what the station reported."""

    ok: bool
    readings: Mapping[str, Any] = field(default_factory=dict[str, Any])


class StationAdapterInterface(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """The adapter's name, as a run's record names what served it."""
        ...

    @property
    @abstractmethod
    def provenance(self) -> str:
        """`real` for the station itself, `twin` for a stand-in."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """The station's declared controlled stop. It needs nothing from the
        platform, so it works when the platform is slow or gone."""
        ...

    @abstractmethod
    async def restore(self) -> None:
        """The station back at its baseline."""
        ...

    @abstractmethod
    async def run(self, operation: str, parameters: Mapping[str, Any]) -> Outcome:
        """One operation the guard let through."""
        ...


class StationTwinImpl(StationAdapterInterface):
    """The twin of a station: it holds the station's state as values,
    applies an operation's parameters to it, and reports them back. It
    keeps what it was asked to do, in order, for a reader to check."""

    def __init__(self, station: Station) -> None:
        self._station = station
        self.state: dict[str, Any] = dict(station.baseline)
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        return f"twin:{self._station.name}"

    @property
    def provenance(self) -> str:
        return "twin"

    async def stop(self) -> None:
        self.calls.append(f"stop:{self._station.controlled_stop}")

    async def restore(self) -> None:
        self.state = dict(self._station.baseline)
        self.calls.append("restore")

    async def run(self, operation: str, parameters: Mapping[str, Any]) -> Outcome:
        self.calls.append(operation)
        self.state.update(parameters)
        return Outcome(ok=True, readings=dict(self.state))


def adapter_for(station: Station) -> StationAdapterInterface:
    """The adapter a station names. Only the twin is carried here."""
    if station.adapter == "twin":
        return StationTwinImpl(station)
    raise ValueError(f"no adapter {station.adapter}")
