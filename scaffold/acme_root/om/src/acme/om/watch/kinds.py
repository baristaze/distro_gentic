"""The kinds of live stream, as a registry. A stream kind is a name and what
each stream of it may hold: its entries, its bytes, and the open streams of
one group. The open streams of every group at once and the idle time bound
the shared cache, every kind's streams together, so they are the step's
alone, never a kind's own. The platform's own kind, the parts of a step,
registers here as a product's kind does at its roots
(`root.PlatformPorts.kinds`), so no stream is written without a bound. A
product's kind may name the claimant kind that writes it through the
gateway, and the one that reads it there, for the item one of its claimants
holds."""

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from uuid import UUID

from acme.infra.streams import StreamBounds, StreamSlice

STREAM_KIND = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

MAX_APPEND_ENTRIES = 64
"""The most entries one append through the gateway carries."""

MAX_APPEND_BYTES = 64 * 1024
"""The most bytes of entries one append through the gateway carries."""

STEP = "step"
"""The platform's stream kind: the parts of one step of a session, in a
group per session, which the stream service writes (`StreamServiceImpl`)."""


@dataclass(frozen=True)
class StreamKind:
    """A kind of live stream and what each stream of it may hold: past its
    entries or its bytes the oldest goes, never the newest, and past its
    open streams of one group the one that heard nothing longest goes.
    `claimant` is the product's claimant kind that writes its streams
    through the gateway, one group per item a claimant of that kind holds;
    None for a kind only the product's own code writes. `reader` is the
    product's claimant kind that reads them through the gateway, for the
    item it holds; None for a kind no claimant reads."""

    name: str
    entries: int
    bytes: int
    streams: int
    claimant: str | None = None
    reader: str | None = None

    def __post_init__(self) -> None:
        if not STREAM_KIND.match(self.name):
            raise ValueError(f"a stream kind is named in lower case, never {self.name!r}")
        if min(self.entries, self.bytes, self.streams) <= 0:
            raise ValueError("every bound of a stream is positive")


class StreamKinds:
    """The stream kinds a process knows, each once, under the shared
    cache's bounds: the open streams of every group at once, and the idle
    time. A kind registered twice is refused, so a product never loosens the
    step's bounds."""

    def __init__(self, kinds: Iterable[StreamKind], *, open: int, idle: timedelta) -> None:
        found: dict[str, StreamKind] = {}
        for kind in kinds:
            if kind.name in found:
                raise ValueError(f"stream kind {kind.name} is registered twice")
            found[kind.name] = kind
        self._kinds: Mapping[str, StreamKind] = MappingProxyType(found)
        self._open = open
        self._idle = idle

    def bounds(self, name: str) -> StreamBounds | None:
        """Every bound a stream of the kind is held to; None for a kind
        nobody registered."""
        kind = self._kinds.get(name)
        if kind is None:
            return None
        return StreamBounds(
            entries=kind.entries,
            bytes=kind.bytes,
            streams=kind.streams,
            open=self._open,
            idle=self._idle,
        )

    def writer(self, name: str) -> str | None:
        """The claimant kind that writes the kind's streams through the
        gateway; None for a kind none writes, or one nobody registered."""
        kind = self._kinds.get(name)
        return None if kind is None else kind.claimant

    def reader(self, name: str) -> str | None:
        """The claimant kind that reads the kind's streams through the
        gateway; None for a kind none reads, or one nobody registered."""
        kind = self._kinds.get(name)
        return None if kind is None else kind.reader


class KindStreamsInterface(ABC):
    """The live streams of a product's kinds: numbered entries in a group,
    each kind held to its registered bounds, as the step's parts are held to
    theirs. A group is the kind's own, so one kind never reads another's
    streams. A kind nobody registered is refused (`NotFound`), and the step
    is the stream service's alone."""

    @abstractmethod
    async def append(
        self, kind: str, group: UUID, stream: UUID, entries: Sequence[tuple[int, bytes]]
    ) -> None:
        """Appends the numbered entries to the stream, past its bounds the
        oldest going first, never the newest."""
        ...

    @abstractmethod
    async def read(
        self, kind: str, group: UUID, after: Mapping[UUID, int]
    ) -> tuple[StreamSlice, ...]:
        """The group's open streams of the kind, each after the number
        `after` names for it."""
        ...

    @abstractmethod
    async def end(self, kind: str, group: UUID, stream: UUID) -> None:
        """Closes the stream: what it held goes at once."""
        ...

    @abstractmethod
    def writer(self, kind: str) -> str | None:
        """The claimant kind that writes a product's kind through the
        gateway; None for the step's, a kind none writes, and one nobody
        registered."""
        ...

    @abstractmethod
    def reader(self, kind: str) -> str | None:
        """The claimant kind that reads a product's kind through the
        gateway; None for the step's, a kind none reads, and one nobody
        registered."""
        ...
