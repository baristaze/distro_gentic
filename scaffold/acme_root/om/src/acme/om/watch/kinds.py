"""The kinds of live stream, as a registry. A stream kind is a name and the
bounds every stream of it is held to: its entries, its bytes, the open
streams of one group and of every group at once, and its idle time. The
platform's own, the parts of a step, registers here as a product's kind
does at its root (`build_stream(product_kinds=...)`), so no stream is written
without a bound."""

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

from acme.infra.streams import StreamBounds, StreamSlice

STREAM_KIND = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

STEP = "step"
"""The platform's stream kind: the parts of one step of a session, in a
group per session, which the stream service writes (`StreamServiceImpl`)."""


@dataclass(frozen=True)
class StreamKind:
    """A kind of live stream and the bounds every stream of it is held to,
    which `StreamBounds` holds positive."""

    name: str
    bounds: StreamBounds

    def __post_init__(self) -> None:
        if not STREAM_KIND.match(self.name):
            raise ValueError(f"a stream kind is named in lower case, never {self.name!r}")


class StreamKinds:
    """The stream kinds a process knows, each once: a kind registered twice
    is refused, so a product never loosens the step's bounds."""

    def __init__(self, kinds: Iterable[StreamKind]) -> None:
        found: dict[str, StreamKind] = {}
        for kind in kinds:
            if kind.name in found:
                raise ValueError(f"stream kind {kind.name} is registered twice")
            found[kind.name] = kind
        self._kinds: Mapping[str, StreamKind] = MappingProxyType(found)

    def __iter__(self) -> Iterator[StreamKind]:
        return iter(self._kinds.values())

    def get(self, name: str) -> StreamKind | None:
        return self._kinds.get(name)


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
