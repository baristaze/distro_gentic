"""Streams: short, numbered logs on the shared cache, for what is read live
while it is written. A stream is the entries of one thing being written,
numbered from 0 in the order they are written, and it sits in a group whose
open streams are read together.

Every stream is bounded: its entries, its bytes, the open streams of its
group, and the open streams of every group at once. Past a bound the
oldest goes, never the newest, and a stream that hears nothing for its
idle time goes whole. A stream is a cache: what its entries add up to is
held whole elsewhere, so losing an entry, or the whole stream, loses no
fact. So a backend that cannot be reached drops an append and reads
nothing, and never raises."""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID


@dataclass(frozen=True)
class StreamBounds:
    """What one stream, one group, and every group at once may hold."""

    entries: int = 1024  # the most entries one stream holds
    bytes: int = 256 * 1024  # the most bytes of entries one stream holds
    streams: int = 16  # the most open streams of one group
    open: int = 4096  # the most open streams of every group at once
    idle: timedelta = timedelta(minutes=2)  # a stream that hears nothing this long goes

    def __post_init__(self) -> None:
        if min(self.entries, self.bytes, self.streams, self.open) <= 0:
            raise ValueError("every bound of a stream is positive")
        if self.idle <= timedelta(0):
            raise ValueError("a stream's idle time is positive")


@dataclass(frozen=True)
class StreamSlice:
    """One open stream as a reader gets it: the number of the oldest entry it
    still holds, and its entries after the reader's mark, each with its
    number, in order."""

    stream: UUID
    first: int
    entries: tuple[tuple[int, bytes], ...] = ()


class StreamsInterface(ABC):
    @abstractmethod
    async def append(
        self,
        group: UUID,
        stream: UUID,
        entries: Sequence[tuple[int, bytes]],
        bounds: StreamBounds,
    ) -> None:
        """Appends each numbered entry to the stream of the group, opening it
        when it is not open. An entry numbered at or below the stream's last
        lands nothing, so an entry sent again, or out of its order, is
        dropped. Opening a stream past its group's bound, or past the bound
        of every group, closes the one that heard nothing longest."""
        ...

    @abstractmethod
    async def read(
        self, group: UUID, after: Mapping[UUID, int], bounds: StreamBounds
    ) -> tuple[StreamSlice, ...]:
        """The group's open streams, the one that heard nothing longest first,
        each with its entries after the number `after` names for it, or every
        entry it holds when `after` names none. Only the group's own."""
        ...

    @abstractmethod
    async def end(self, group: UUID, stream: UUID) -> None:
        """Closes the stream: what it held goes at once."""
        ...

    @abstractmethod
    def describe(self) -> str: ...

    @abstractmethod
    async def start(self) -> None:
        """Opened by the infra root at boot. An impl that holds no connection
        of its own returns None."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Closed by the infra root at shutdown, in reverse order of start."""
        ...
