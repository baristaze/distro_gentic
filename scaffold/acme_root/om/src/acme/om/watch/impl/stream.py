import asyncio
import logging
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from pydantic import Field, TypeAdapter, ValidationError

from acme.infra.streams import StreamBounds, StreamsInterface
from acme.infra.topics import EntityChangedPayload, Topics, TopicsInterface
from acme.om.base import Platform, new_id
from acme.om.context import TenantContext
from acme.om.events import EventsManagerInterface
from acme.om.events.manager import audit_event
from acme.om.steps.types.stream import StreamPart
from acme.om.watch.stream import StreamServiceInterface
from acme.om.watch.types.live import LiveStream, Seen

log = logging.getLogger(__name__)

OPENED = "watch.stream.opened"
COMPLETED = "watch.stream.completed"
"""The changes a stream makes, each recorded in the tenant's event stream
under its session, naming its step, and hinted on the realtime channel."""

PARTS: TypeAdapter[StreamPart] = TypeAdapter(StreamPart)


class StreamOptions(Platform):
    # The most parts, and the most bytes of them, one stream holds: past
    # either, its oldest part goes, never its newest.
    max_parts: int = Field(default=1024, gt=0)
    max_bytes: int = Field(default=256 * 1024, gt=0)
    # The most open streams of one session, and of every session at once:
    # past either, the stream that heard nothing longest goes.
    max_streams: int = Field(default=16, gt=0)
    max_open: int = Field(default=4096, gt=0)
    # A stream that hears nothing this long is closed: its step is stored.
    idle: timedelta = Field(default=timedelta(minutes=2), gt=timedelta(0))
    # The most parts and changes waiting in this process to be written: past
    # it, the oldest goes, never the newest, and the loop never waits.
    max_queued: int = Field(default=4096, gt=0)

    def bounds(self) -> StreamBounds:
        return StreamBounds(
            entries=self.max_parts,
            bytes=self.max_bytes,
            streams=self.max_streams,
            open=self.max_open,
            idle=self.idle,
        )


@dataclass(frozen=True)
class _Change:
    """A stream opened or completed, under the run's context."""

    kind: str
    ctx: TenantContext
    session_id: UUID
    step_id: UUID


class StreamServiceImpl(StreamServiceInterface):
    """The parts this process emits, queued in their order and written to
    the shared cache's streams by one task, so an emit never waits and a
    stream's parts land in order: a stream per step, in a group per session.
    A stream's opening and its completion are written in that order too:
    each is an entry in the tenant's event stream and a hint on the channel,
    and completing ends the stream, since its step holds it whole. `events`
    is read when a change is written, so a root can build this before the
    managers whose loop it is the sink of."""

    def __init__(
        self,
        streams: StreamsInterface,
        topics: TopicsInterface,
        events: Callable[[], EventsManagerInterface],
        options: StreamOptions | None = None,
    ) -> None:
        self._streams = streams
        self._topics = topics
        self._events = events
        self._options = options or StreamOptions()
        self._bounds = self._options.bounds()
        self._queue: deque[StreamPart | _Change] = deque(maxlen=self._options.max_queued)
        self._writer: asyncio.Task[None] | None = None
        self._overflowed = False

    def emit(self, part: StreamPart) -> None:
        self._put(part)

    def opened(self, ctx: TenantContext, session_id: UUID, step_id: UUID) -> None:
        self._put(_Change(OPENED, ctx, session_id, step_id))

    def completed(self, ctx: TenantContext, session_id: UUID, step_id: UUID) -> None:
        self._put(_Change(COMPLETED, ctx, session_id, step_id))

    async def read(self, session_id: UUID, seen: Sequence[Seen]) -> tuple[LiveStream, ...]:
        after = {mark.step_id: mark.n for mark in seen}
        streams: list[LiveStream] = []
        for held in await self._streams.read(session_id, after, self._bounds):
            parts = tuple(
                part
                for part in (_part(entry) for _, entry in held.entries)
                # A part is the stream's only when it names its session and
                # its step: nothing else in the cache reaches this reader.
                if part is not None and (part.session_id, part.step_id) == (session_id, held.stream)
            )
            last = after.get(held.stream, -1)
            streams.append(
                LiveStream(
                    step_id=held.stream,
                    first=held.first,
                    parts=parts,
                    dropped=last + 1 < held.first,
                )
            )
        return tuple(streams)

    async def flush(self) -> None:
        """Waits until what is queued now is written."""
        while self._writer is not None and not self._writer.done():
            await asyncio.wait({self._writer})

    async def close(self) -> None:
        await self.flush()

    def _put(self, item: StreamPart | _Change) -> None:
        if len(self._queue) == self._queue.maxlen and not self._overflowed:
            self._overflowed = True
            log.warning("the stream service is behind: the oldest queued parts go")
        self._queue.append(item)
        if self._writer is None or self._writer.done():
            self._writer = asyncio.get_running_loop().create_task(self._write())

    async def _write(self) -> None:
        while self._queue:
            item = self._queue.popleft()
            try:
                if isinstance(item, _Change):
                    await self._change(item)
                else:
                    await self._append(item)
            except Exception:
                log.warning(
                    "the stream service failed a write: the live view lost it", exc_info=True
                )
        self._overflowed = False

    async def _append(self, first: StreamPart) -> None:
        """The part and every part queued right behind it in its stream, in
        one append."""
        batch = [first]
        while self._queue:
            behind = self._queue[0]
            if isinstance(behind, _Change) or (behind.session_id, behind.step_id) != (
                first.session_id,
                first.step_id,
            ):
                break
            self._queue.popleft()
            batch.append(behind)
        await self._streams.append(
            first.session_id,
            first.step_id,
            [(part.n, PARTS.dump_json(part)) for part in batch],
            self._bounds,
        )

    async def _change(self, change: _Change) -> None:
        if change.kind == COMPLETED:
            await self._streams.end(change.session_id, change.step_id)
        ctx = change.ctx
        event = await self._events().append_event(
            ctx,
            audit_event(
                ctx, new_id(), change.kind, change.session_id, {"step_id": str(change.step_id)}
            ),
        )
        await self._topics.publish(
            Topics.ENTITY_CHANGED,
            EntityChangedPayload(
                idempotency_key=event.id,
                produced_at=event.produced_at,
                org_id=event.org_id,
                kind=event.kind,
                target_id=event.target_id,
                seq=event.seq,
                actor_id=event.actor_id,
            ),
        )


def _part(entry: bytes) -> StreamPart | None:
    """A part as the cache holds it; an entry that is not one reads as
    nothing, never an error."""
    try:
        return PARTS.validate_json(entry)
    except ValidationError:
        return None
