"""The streams breaker: the cost bound in front of streams that live out of
process, a decoration like the cache's (`cache/breaker.py`). An open breaker
answers as a backend that cannot be reached does: an append or an end is
dropped, and a read finds nothing open. The live view loses what it would
have shown, and the record it is a window onto loses nothing."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from acme.infra.breaker import Breaker
from acme.infra.streams import StreamBounds, StreamsInterface, StreamSlice


class StreamsBreakerImpl(StreamsInterface):
    def __init__(self, inner: StreamsInterface, breaker: Breaker) -> None:
        self._inner = inner
        self._breaker = breaker

    async def append(
        self,
        group: UUID,
        stream: UUID,
        entries: Sequence[tuple[int, bytes]],
        bounds: StreamBounds,
    ) -> None:
        if not self._breaker.allows():
            return None
        with self._breaker.measured():
            await self._inner.append(group, stream, entries, bounds)

    async def read(
        self, group: UUID, after: Mapping[UUID, int], bounds: StreamBounds
    ) -> tuple[StreamSlice, ...]:
        if not self._breaker.allows():
            return ()
        with self._breaker.measured():
            return await self._inner.read(group, after, bounds)

    async def end(self, group: UUID, stream: UUID) -> None:
        if not self._breaker.allows():
            return None
        with self._breaker.measured():
            await self._inner.end(group, stream)

    def describe(self) -> str:
        return f"{self._inner.describe()}+{self._breaker.describe()}"

    async def start(self) -> None:
        await self._inner.start()

    async def close(self) -> None:
        await self._inner.close()
