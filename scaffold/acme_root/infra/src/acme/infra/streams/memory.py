from collections import OrderedDict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from acme.infra.base import utcnow
from acme.infra.streams import StreamBounds, StreamsInterface, StreamSlice

_Key = tuple[UUID, UUID]  # a group and a stream of it


@dataclass
class _Stream:
    heard_at: datetime
    entries: deque[tuple[int, bytes]] = field(default_factory=deque[tuple[int, bytes]])
    size: int = 0
    last: int = -1


class StreamsMemoryImpl(StreamsInterface):
    """Every open stream in this process, each a bounded buffer: one process's
    own, as the memory cache is. Nothing is awaited, so an append and a read
    never interleave."""

    def __init__(self, clock: Callable[[], datetime] = utcnow) -> None:
        self._clock = clock
        # Every open stream, the one that heard nothing longest first; and
        # each group's, in the same order.
        self._streams: OrderedDict[_Key, _Stream] = OrderedDict()
        self._groups: dict[UUID, OrderedDict[UUID, None]] = {}

    async def append(
        self,
        group: UUID,
        stream: UUID,
        entries: Sequence[tuple[int, bytes]],
        bounds: StreamBounds,
    ) -> None:
        now = self._clock()
        self._expire(now, bounds)
        key = (group, stream)
        held = self._streams.get(key)
        for n, entry in entries:
            last = -1 if held is None else held.last
            if n <= last:
                continue
            if held is None:
                held = self._open(key, now, bounds)
            while held.entries and (
                len(held.entries) >= bounds.entries or held.size + len(entry) > bounds.bytes
            ):
                held.size -= len(held.entries.popleft()[1])
            held.entries.append((n, entry))
            held.size += len(entry)
            held.last = n
            held.heard_at = now
            self._streams.move_to_end(key)
            self._groups[group].move_to_end(stream)

    async def read(
        self, group: UUID, after: Mapping[UUID, int], bounds: StreamBounds
    ) -> tuple[StreamSlice, ...]:
        self._expire(self._clock(), bounds)
        slices: list[StreamSlice] = []
        for stream in self._groups.get(group, OrderedDict[UUID, None]()):
            held = self._streams[(group, stream)]
            if not held.entries:
                continue
            mark = after.get(stream, -1)
            slices.append(
                StreamSlice(
                    stream=stream,
                    first=held.entries[0][0],
                    entries=tuple(item for item in held.entries if item[0] > mark),
                )
            )
        return tuple(slices)

    async def end(self, group: UUID, stream: UUID) -> None:
        if (group, stream) in self._streams:
            self._close((group, stream))

    def _open(self, key: _Key, now: datetime, bounds: StreamBounds) -> _Stream:
        group, stream = key
        own = self._groups.setdefault(group, OrderedDict())
        if len(own) >= bounds.streams:
            self._close((group, next(iter(own))))
        if len(self._streams) >= bounds.open:
            self._close(next(iter(self._streams)))
        held = _Stream(heard_at=now)
        self._streams[key] = held
        self._groups.setdefault(group, OrderedDict())[stream] = None
        return held

    def _expire(self, now: datetime, bounds: StreamBounds) -> None:
        while self._streams:
            key, held = next(iter(self._streams.items()))
            if held.heard_at + bounds.idle > now:
                return
            self._close(key)

    def _close(self, key: _Key) -> None:
        group, stream = key
        del self._streams[key]
        own = self._groups[group]
        del own[stream]
        if not own:
            del self._groups[group]

    def describe(self) -> str:
        return "streams=memory"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None
