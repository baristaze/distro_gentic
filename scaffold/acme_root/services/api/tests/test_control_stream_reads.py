"""A host's control stream, on a clock the test moves: however many wakes
reach its lanes, it reads the host's control messages no more often than
its spacing allows, and the wakes in between are one read and one wake.
Each stream lives a span drawn as it opens, at most `STREAM_SPAN`."""

import asyncio
import itertools
from datetime import UTC, datetime, timedelta
from uuid import UUID

from acme.infra.base import new_id
from acme.infra.topics import Topics, WorkAvailablePayload
from acme.infra.topics.memory import TopicsMemoryImpl
from acme.om.context import AppContext, AppType, RequestContext
from acme.om.exec_relay.types.exec import ExecControl
from acme.om.hosts.types.host import HostIdentity
from acme.om.placement.rules import pool_lane
from acme.services.api.services.impl.exec_relay import (
    SPAN_JITTER,
    STREAM_SPAN,
    ExecRelayServiceImpl,
)
from acme.services.api.types.exec_relay import ControlKind

OPENED = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
SPACING = timedelta(seconds=1)
HOST = HostIdentity(
    kind="host",
    id=new_id(),
    org_id=new_id(),
    pool_id=new_id(),
    credential_id=new_id(),
    expires_at=OPENED + timedelta(days=1),
)


class Clock:
    """The stream's clock, which only its sleeps move."""

    def __init__(self) -> None:
        self.now = OPENED

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        await asyncio.sleep(0)


class Relay:
    """The relay's control reads, each stamped on the clock. With a `burst`,
    each read is followed at once by that many enqueues on the host's pool
    lane, so a wake is always waiting when the stream looks."""

    def __init__(self, clock: Clock, topics: TopicsMemoryImpl, burst: int) -> None:
        self.reads: list[datetime] = []
        self._clock = clock
        self._topics = topics
        self._burst = burst

    async def controls(
        self, rctx: RequestContext, host: HostIdentity, after: UUID | None
    ) -> list[ExecControl]:
        self.reads.append(self._clock())
        for _ in range(self._burst):
            await self._topics.publish(
                Topics.WORK_AVAILABLE,
                WorkAvailablePayload(
                    idempotency_key=new_id(),
                    produced_at=self._clock(),
                    org_id=host.org_id,
                    lane=pool_lane(host.pool_id),
                    kind="exec",
                ),
            )
        return []


def stream_of(
    burst: int, jitter: float, poll: timedelta = timedelta(seconds=5)
) -> tuple[ExecRelayServiceImpl, Relay, Clock]:
    clock = Clock()
    topics = TopicsMemoryImpl()
    relay = Relay(clock, topics, burst)
    service = ExecRelayServiceImpl(
        relay,  # type: ignore[arg-type]
        topics,
        poll=poll,
        spacing=SPACING,
        clock=clock,
        sleep=clock.sleep,
        jitter=lambda: jitter,
    )
    return service, relay, clock


def a_request() -> RequestContext:
    return RequestContext(request_id=new_id(), app=AppContext(type=AppType.API, version="t"))


async def test_a_burst_of_wakes_reads_the_hosts_controls_no_faster_than_the_spacing() -> None:
    service, relay, _ = stream_of(burst=20, jitter=0.0)
    wakes = 0
    async for view in service.control(a_request(), HOST, None):
        if view.kind is ControlKind.WAKE:
            wakes += 1
        if len(relay.reads) == 10:
            break
    gaps = [later - earlier for earlier, later in itertools.pairwise(relay.reads)]
    assert len(gaps) == 9 and min(gaps) >= SPACING, gaps
    # The one at the open, and one for each read's burst of twenty.
    assert wakes == len(relay.reads) + 1


async def test_each_stream_ends_within_a_span_drawn_below_the_most() -> None:
    for jitter, span in ((0.0, STREAM_SPAN), (1.0, STREAM_SPAN * (1 - SPAN_JITTER))):
        service, relay, clock = stream_of(burst=0, jitter=jitter, poll=timedelta(milliseconds=1))
        async for _ in service.control(a_request(), HOST, None):
            pass
        assert clock.now - OPENED == span
        assert relay.reads[-1] - relay.reads[0] == span
