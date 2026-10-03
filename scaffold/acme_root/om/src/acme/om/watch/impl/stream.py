import asyncio
import logging
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
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
from acme.om.watch.kinds import STEP, StreamKind, StreamKinds
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
    # A stream writes at most once a window, however fast its parts come:
    # the first part after a quiet window goes at once, and the parts behind
    # it are joined, one entry for each run of a block's parts, until the
    # window ends, a new block starts, the stream completes, or the run's
    # text reaches `join_bytes`. Zero writes each part as it comes.
    window: timedelta = Field(default=timedelta(milliseconds=100), ge=timedelta(0))
    join_bytes: int = Field(default=16 * 1024, gt=0)

    def bounds(self) -> StreamBounds:
        return StreamBounds(
            entries=self.max_parts,
            bytes=self.max_bytes,
            streams=self.max_streams,
            open=self.max_open,
            idle=self.idle,
        )


def step_kinds(options: StreamOptions, *kinds: StreamKind) -> StreamKinds:
    """The step kind under the bounds `options` set, the platform's own, and
    a product's `kinds` beside it."""
    return StreamKinds((StreamKind(STEP, options.bounds()), *kinds))


@dataclass(frozen=True)
class _Change:
    """A stream opened or completed, under the run's context."""

    kind: str
    ctx: TenantContext
    session_id: UUID
    step_id: UUID


@dataclass
class _Held:
    """A stream that wrote within its window, and the parts it holds until
    the window ends. A stream with none goes at once."""

    timer: asyncio.TimerHandle
    parts: list[StreamPart] = field(default_factory=lambda: [])
    size: int = 0  # the bytes of the held parts' text


class StreamServiceImpl(StreamServiceInterface):
    """The parts this process emits, queued in their order and written to
    the shared cache's streams by one task, so an emit never waits and a
    stream's parts land in order: a stream per step, in a group per session.
    A stream's opening and its completion are written in that order too:
    each is an entry in the tenant's event stream and a hint on the channel,
    and completing ends the stream, since its step holds it whole. A
    stream's parts are joined for its window first, so the cache sees a
    write a window, not a write a part. `events` is read when a change is
    written, so a root can build this before the managers whose loop it is
    the sink of. Its bounds are the step kind's, as the stream kinds'
    registry holds them (`step_kinds`)."""

    def __init__(
        self,
        streams: StreamsInterface,
        topics: TopicsInterface,
        events: Callable[[], EventsManagerInterface],
        options: StreamOptions | None = None,
        kinds: StreamKinds | None = None,
    ) -> None:
        self._streams = streams
        self._topics = topics
        self._events = events
        self._options = options or StreamOptions()
        step = (kinds or step_kinds(self._options)).get(STEP)
        if step is None:
            raise ValueError("the stream service writes the step kind, which is not registered")
        self._bounds = step.bounds
        self._queue: deque[StreamPart | _Change] = deque(maxlen=self._options.max_queued)
        self._writer: asyncio.Task[None] | None = None
        self._overflowed = False
        self._window = self._options.window.total_seconds()
        self._held: dict[tuple[UUID, UUID], _Held] = {}

    def emit(self, part: StreamPart) -> None:
        if not self._window:
            self._put(part)
            return
        key = (part.session_id, part.step_id)
        held = self._held.get(key)
        if held is None:
            # Quiet for a window: the part goes at once, and those behind it
            # wait for the window's end.
            self._put(part)
            self._held[key] = _Held(self._later(key))
            return
        if held.parts and not _continues(held.parts[-1], part):
            self._release(held)
        held.parts.append(part)
        held.size += len(part.text.encode())
        if held.size >= self._options.join_bytes:
            self._release(held)

    def opened(self, ctx: TenantContext, session_id: UUID, step_id: UUID) -> None:
        self._put(_Change(OPENED, ctx, session_id, step_id))

    def completed(self, ctx: TenantContext, session_id: UUID, step_id: UUID) -> None:
        held = self._held.pop((session_id, step_id), None)
        if held is not None:
            held.timer.cancel()
            self._release(held)
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
        """Writes what each stream holds now, and waits until what is queued
        is written."""
        for held in self._held.values():
            self._release(held)
        while self._writer is not None and not self._writer.done():
            await asyncio.wait({self._writer})

    async def close(self) -> None:
        for held in self._held.values():
            held.timer.cancel()
        await self.flush()
        self._held.clear()

    def _later(self, key: tuple[UUID, UUID]) -> asyncio.TimerHandle:
        return asyncio.get_running_loop().call_later(self._window, self._tick, key)

    def _tick(self, key: tuple[UUID, UUID]) -> None:
        """A stream's window ends: what it held goes, and the next window
        starts; a stream that held nothing is quiet again."""
        held = self._held.get(key)
        if held is None:
            return
        if not held.parts:
            del self._held[key]
            return
        self._release(held)
        held.timer = self._later(key)

    def _release(self, held: _Held) -> None:
        """Queues what a stream holds, as one part."""
        if held.parts:
            parts, held.parts, held.size = held.parts, [], 0
            self._put(_joined(parts))

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
            [(part.n, PARTS.dump_json(part, exclude_none=True)) for part in batch],
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


def _continues(before: StreamPart, part: StreamPart) -> bool:
    """`part` is the next place of the block `before` is in: its stream,
    its kind, its block, and its channel or its call the same."""
    return part.n == before.end + 1 and _block(part) == _block(before)


def _block(part: StreamPart) -> dict[str, object]:
    return part.model_dump(exclude={"n", "last", "text"})


def _joined(parts: Sequence[StreamPart]) -> StreamPart:
    """A run of one block's parts as one: the first's place, the last's as
    its `last`, and their text in order."""
    first = parts[0]
    if len(parts) == 1:
        return first
    return first.model_copy(
        update={"last": parts[-1].end, "text": "".join(part.text for part in parts)}
    )


def _part(entry: bytes) -> StreamPart | None:
    """A part as the cache holds it; an entry that is not one reads as
    nothing, never an error."""
    try:
        return PARTS.validate_json(entry)
    except ValidationError:
        return None
