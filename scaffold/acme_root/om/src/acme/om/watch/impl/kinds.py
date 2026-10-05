from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import UUID

from acme.infra.streams import StreamBounds, StreamsInterface, StreamSlice
from acme.om.base import derived_id
from acme.om.exceptions import NotFound
from acme.om.watch.kinds import STEP, KindStreamsInterface, StreamKinds


class KindStreamsImpl(KindStreamsInterface):
    """A product's live streams on infra's streams, the shared cache's, each
    kind under its registered bounds and in a group of its own: the group a
    caller names, keyed by the kind, so no kind reads another's. Every
    kind's streams count against the cache's bounds together, the step's
    among them, as every session's do."""

    def __init__(self, streams: StreamsInterface, kinds: StreamKinds) -> None:
        self._streams = streams
        self._kinds = kinds

    async def append(
        self, kind: str, group: UUID, stream: UUID, entries: Sequence[tuple[int, bytes]]
    ) -> None:
        await self._streams.append(_group(kind, group), stream, entries, self._bounds(kind))

    async def read(
        self, kind: str, group: UUID, after: Mapping[UUID, int]
    ) -> tuple[StreamSlice, ...]:
        return await self._streams.read(_group(kind, group), after, self._bounds(kind))

    async def end(self, kind: str, group: UUID, stream: UUID) -> None:
        self._bounds(kind)
        await self._streams.end(_group(kind, group), stream)

    def writer(self, kind: str) -> str | None:
        return None if kind == STEP else self._kinds.writer(kind)

    def reader(self, kind: str) -> str | None:
        return None if kind == STEP else self._kinds.reader(kind)

    def _bounds(self, kind: str) -> StreamBounds:
        """The bounds of a product's registered kind; the step is the stream
        service's, and a kind nobody registered has none, so it is refused."""
        found = self._kinds.bounds(kind)
        if kind == STEP or found is None:
            raise NotFound(f"no stream kind {kind} is registered for a product")
        return found


_GROUPS_AT = datetime(2000, 1, 1, tzinfo=UTC)
"""The one time a kind's groups are derived at, so a caller's group of one
kind is the same group at every call."""


def _group(kind: str, group: UUID) -> UUID:
    """The kind's own group of the one a caller names."""
    return derived_id(group, _GROUPS_AT, kind)
