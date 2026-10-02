from collections import OrderedDict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field

from acme.om.base import Platform, utcnow
from acme.om.steps.types.stream import StreamPart
from acme.om.watch.stream import StreamServiceInterface
from acme.om.watch.types.live import LiveStream, Seen


class StreamOptions(Platform):
    # The most parts, and the most bytes of text, one stream holds: past
    # either, its oldest part goes, never its newest.
    max_parts: int = Field(default=1024, gt=0)
    max_bytes: int = Field(default=256 * 1024, gt=0)
    # The most open streams of one session, and of every session at once:
    # past either, the stream that heard nothing longest goes.
    max_streams: int = Field(default=16, gt=0)
    max_open: int = Field(default=4096, gt=0)
    # A stream that hears nothing this long is closed: its step is stored.
    idle: timedelta = Field(default=timedelta(minutes=2), gt=timedelta(0))


@dataclass
class _Buffer:
    session_id: UUID
    heard_at: datetime
    parts: deque[StreamPart] = field(default_factory=deque[StreamPart])
    size: int = 0
    last: int = -1


def _size(part: StreamPart) -> int:
    return len(part.text.encode())


class StreamServiceMemoryImpl(StreamServiceInterface):
    """Every open stream in this process, each a bounded buffer. A part
    sent again, or out of its order, lands nothing. Nothing is awaited, so
    an emit and a read never interleave."""

    def __init__(
        self, options: StreamOptions | None = None, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._options = options or StreamOptions()
        self._clock = clock
        # Every open stream by its step, the one that heard nothing longest
        # first; and each session's, in the same order.
        self._streams: OrderedDict[UUID, _Buffer] = OrderedDict()
        self._sessions: dict[UUID, OrderedDict[UUID, None]] = {}

    def emit(self, part: StreamPart) -> None:
        now = self._clock()
        self._expire(now)
        buffer = self._streams.get(part.step_id)
        if buffer is None:
            buffer = self._open(part.session_id, part.step_id, now)
        elif buffer.session_id != part.session_id:
            # A step belongs to one session: a part that names another is
            # not this stream's.
            return
        if part.n <= buffer.last:
            return
        buffer.parts.append(part)
        buffer.size += _size(part)
        buffer.last = part.n
        buffer.heard_at = now
        while len(buffer.parts) > 1 and (
            len(buffer.parts) > self._options.max_parts or buffer.size > self._options.max_bytes
        ):
            buffer.size -= _size(buffer.parts.popleft())
        self._streams.move_to_end(part.step_id)
        self._sessions[part.session_id].move_to_end(part.step_id)

    def read(self, session_id: UUID, seen: Sequence[Seen]) -> tuple[LiveStream, ...]:
        self._expire(self._clock())
        after = {mark.step_id: mark.n for mark in seen}
        streams: list[LiveStream] = []
        for step_id in self._sessions.get(session_id, OrderedDict[UUID, None]()):
            buffer = self._streams[step_id]
            if not buffer.parts:
                continue
            last = after.get(step_id, -1)
            first = buffer.parts[0].n
            streams.append(
                LiveStream(
                    step_id=step_id,
                    first=first,
                    parts=tuple(part for part in buffer.parts if part.n > last),
                    dropped=last + 1 < first,
                )
            )
        return tuple(streams)

    def _open(self, session_id: UUID, step_id: UUID, now: datetime) -> _Buffer:
        own = self._sessions.setdefault(session_id, OrderedDict())
        if len(own) >= self._options.max_streams:
            self._close(next(iter(own)))
        if len(self._streams) >= self._options.max_open:
            self._close(next(iter(self._streams)))
        buffer = _Buffer(session_id=session_id, heard_at=now)
        self._streams[step_id] = buffer
        self._sessions.setdefault(session_id, OrderedDict())[step_id] = None
        return buffer

    def _expire(self, now: datetime) -> None:
        while self._streams:
            step_id, buffer = next(iter(self._streams.items()))
            if buffer.heard_at + self._options.idle > now:
                return
            self._close(step_id)

    def _close(self, step_id: UUID) -> None:
        buffer = self._streams.pop(step_id)
        own = self._sessions[buffer.session_id]
        del own[step_id]
        if not own:
            del self._sessions[buffer.session_id]
