"""A product's claimant's control stream, over a stand-in for what it
holds and the bus in memory: it carries the wakes of its own lanes and
kinds, the revokes of its own items, and the appends to streams its kind
reads for its own items, and nothing of another claimant's, another
kind's, or another tenant's. It ends with its credential, once the
claimant is revoked, and within a span drawn as it opens."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from acme.infra.base import new_id
from acme.infra.topics import StreamAppendedPayload, Topics, WorkAvailablePayload
from acme.infra.topics.memory import TopicsMemoryImpl
from acme.om.base import utcnow
from acme.om.context import AppContext, AppType, RequestContext
from acme.om.exceptions import CredentialExpired
from acme.om.hosts.types.host import ClaimantIdentity
from acme.om.placement.types.claimant import Holding
from acme.services.api.services.impl.exec_relay import SPAN_JITTER, STREAM_SPAN
from acme.services.api.services.impl.hosts import HostsServiceImpl
from acme.services.api.types.hosts import ClaimantControlKind, ClaimantControlView

SCAN, PROBE = "SCAN", "PROBE"
SCANNER, PROBER = "scanner", "prober"
CUES, PROBE_CUES = "scan_cues", "probe_cues"
READERS = {CUES: SCANNER, PROBE_CUES: PROBER}
POLL = timedelta(milliseconds=200)
QUIET = 0.5  # longer than a poll and its settle: what did not come by then never comes


def a_claimant(expires_at: datetime | None = None) -> ClaimantIdentity:
    return ClaimantIdentity(
        kind=SCANNER,
        id=new_id(),
        org_id=new_id(),
        pool_id=new_id(),
        credential_id=new_id(),
        expires_at=expires_at or utcnow() + timedelta(days=1),
    )


def lane_of(claimant: ClaimantIdentity) -> str:
    return f"scanner:{claimant.pool_id}"


class Hosts:
    """What the claimant holds, as each read finds it, and when each read
    was; `revoked` refuses every read after it, as a revoked claimant's
    is."""

    def __init__(self, claimant: ClaimantIdentity, clock: Callable[[], datetime] = utcnow) -> None:
        self.items: tuple[tuple[UUID, UUID], ...] = ()
        self.revoked = False
        self.reads: list[datetime] = []
        self._claims = ((lane_of(claimant), (SCAN,)),)
        self._clock = clock

    async def holding_as(self, rctx: RequestContext, claimant: ClaimantIdentity) -> Holding:
        self.reads.append(self._clock())
        if self.revoked:
            raise CredentialExpired("scanner revoked")
        return Holding(claims=self._claims, items=self.items, whole=True)


def a_request() -> RequestContext:
    return RequestContext(request_id=new_id(), app=AppContext(type=AppType.API, version="t"))


def service_of(hosts: Hosts, topics: TopicsMemoryImpl, **timing: object) -> HostsServiceImpl:
    return HostsServiceImpl(
        hosts,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        topics,
        READERS.get,
        **{  # type: ignore[arg-type]
            "poll": POLL,
            "settle": timedelta(milliseconds=20),
            "spacing": timedelta(milliseconds=20),
            **timing,
        },
    )


class Heard:
    """The stream's lines as they come, in a task of their own."""

    def __init__(self, service: HostsServiceImpl, claimant: ClaimantIdentity, items: list[UUID]):
        self.lines: list[ClaimantControlView] = []
        self._line = asyncio.Event()
        self.task = asyncio.ensure_future(self._hear(service, claimant, items))

    async def _hear(
        self, service: HostsServiceImpl, claimant: ClaimantIdentity, items: list[UUID]
    ) -> None:
        async for view in service.control(a_request(), claimant, items):
            self.lines.append(view)
            self._line.set()

    def said(self, kind: ClaimantControlKind) -> list[ClaimantControlView]:
        return [line for line in self.lines if line.kind is kind]

    async def until(self, kind: ClaimantControlKind, count: int, within: float = 2.0) -> None:
        async with asyncio.timeout(within):
            while len(self.said(kind)) < count:
                self._line.clear()
                await self._line.wait()

    async def stop(self) -> None:
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


async def work_on(topics: TopicsMemoryImpl, org_id: UUID, lane: str, kind: str) -> None:
    await topics.publish(
        Topics.WORK_AVAILABLE,
        WorkAvailablePayload(
            idempotency_key=new_id(), produced_at=utcnow(), org_id=org_id, lane=lane, kind=kind
        ),
    )


async def appended_to(topics: TopicsMemoryImpl, org_id: UUID, kind: str, item_id: UUID) -> None:
    await topics.publish(
        Topics.STREAM_APPENDED,
        StreamAppendedPayload(
            idempotency_key=new_id(), produced_at=utcnow(), org_id=org_id, kind=kind, group=item_id
        ),
    )


async def test_a_claimants_stream_carries_its_own_lanes_wakes_and_its_own_items_alone() -> None:
    claimant, other = a_claimant(), a_claimant()
    topics = TopicsMemoryImpl()
    hosts = Hosts(claimant)
    mine, theirs = new_id(), new_id()
    hosts.items = ((mine, new_id()),)
    heard = Heard(service_of(hosts, topics), claimant, [mine])
    try:
        await heard.until(ClaimantControlKind.WAKE, 1)  # the one at the open
        # Another claimant's lane, another kind on its own lane, and another
        # tenant's work on a lane of the same name wake it to claim nothing.
        await work_on(topics, claimant.org_id, lane_of(other), SCAN)
        await work_on(topics, claimant.org_id, lane_of(claimant), PROBE)
        await work_on(topics, other.org_id, lane_of(claimant), SCAN)
        # An append to another claimant's item, to its own item in another
        # tenant's name, and to a kind another claimant kind reads, wakes it
        # to read nothing.
        await appended_to(topics, claimant.org_id, CUES, theirs)
        await appended_to(topics, other.org_id, CUES, mine)
        await appended_to(topics, claimant.org_id, PROBE_CUES, mine)
        await asyncio.sleep(QUIET)
        assert [line.kind for line in heard.lines if line.kind is not ClaimantControlKind.PING] == [
            ClaimantControlKind.WAKE
        ]

        await work_on(topics, claimant.org_id, lane_of(claimant), SCAN)
        await heard.until(ClaimantControlKind.WAKE, 2)
        await appended_to(topics, claimant.org_id, CUES, mine)
        await heard.until(ClaimantControlKind.APPENDED, 1)
        assert heard.said(ClaimantControlKind.APPENDED) == [
            ClaimantControlView(kind=ClaimantControlKind.APPENDED, item_id=mine, stream_kind=CUES)
        ]
        # Its own item, taken back: the revoke names it, and no other.
        hosts.items = ()
        await heard.until(ClaimantControlKind.REVOKE, 1)
        await asyncio.sleep(QUIET)
        assert heard.said(ClaimantControlKind.REVOKE) == [
            ClaimantControlView(kind=ClaimantControlKind.REVOKE, item_id=mine)
        ]
        assert len(heard.said(ClaimantControlKind.WAKE)) == 2
        assert len(heard.said(ClaimantControlKind.APPENDED)) == 1
    finally:
        await heard.stop()


async def test_an_item_it_no_longer_holds_under_its_claim_is_revoked_within_one_read() -> None:
    claimant = a_claimant()
    topics = TopicsMemoryImpl()
    hosts = Hosts(claimant)
    kept, reclaimed, dropped, named = new_id(), new_id(), new_id(), new_id()
    hosts.items = ((kept, new_id()), (reclaimed, new_id()), (dropped, new_id()))
    # It names an item it works on that was taken back while no stream was
    # open: the first read revokes it.
    heard = Heard(service_of(hosts, topics), claimant, [kept, named])
    try:
        await heard.until(ClaimantControlKind.REVOKE, 1)
        assert [line.item_id for line in heard.said(ClaimantControlKind.REVOKE)] == [named]
        # Its lease lapsed and the item was claimed again under another
        # claim, and another was ended: each is revoked at the next read.
        await asyncio.sleep(QUIET)
        taken = utcnow()
        hosts.items = ((kept, hosts.items[0][1]), (reclaimed, new_id()))
        await heard.until(ClaimantControlKind.REVOKE, 2)
        hosts.items = ((kept, hosts.items[0][1]),)
        await heard.until(ClaimantControlKind.REVOKE, 3)
        assert utcnow() - taken <= 2 * POLL + timedelta(milliseconds=100)
        revoked = [line.item_id for line in heard.said(ClaimantControlKind.REVOKE)]
        assert revoked == [named, reclaimed, dropped]
    finally:
        await heard.stop()


async def test_a_claimants_stream_ends_with_its_credential_and_once_it_is_revoked() -> None:
    topics = TopicsMemoryImpl()
    expiring = a_claimant(expires_at=utcnow() + timedelta(milliseconds=300))
    heard = Heard(service_of(Hosts(expiring), topics), expiring, [])
    async with asyncio.timeout(2):
        await heard.task
    assert utcnow() >= expiring.expires_at

    claimant = a_claimant()
    hosts = Hosts(claimant)
    heard = Heard(service_of(hosts, topics), claimant, [])
    await heard.until(ClaimantControlKind.WAKE, 1)
    hosts.revoked = True
    async with asyncio.timeout(2):
        await heard.task
    assert hosts.reads[-1] - hosts.reads[0] <= 2 * POLL + timedelta(milliseconds=100)


class Clock:
    """The stream's clock, which only its sleeps move."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        await asyncio.sleep(0)


async def test_a_claimants_stream_ends_within_a_span_drawn_below_the_most() -> None:
    for jitter, span in ((0.0, STREAM_SPAN), (1.0, STREAM_SPAN * (1 - SPAN_JITTER))):
        clock = Clock()
        opened = clock.now
        claimant = a_claimant(expires_at=opened + timedelta(days=1))
        hosts = Hosts(claimant, clock)
        service = service_of(
            hosts,
            TopicsMemoryImpl(),
            poll=timedelta(milliseconds=1),
            settle=timedelta(milliseconds=1),
            spacing=timedelta(seconds=1),
            clock=clock,
            sleep=clock.sleep,
            jitter=lambda jitter=jitter: jitter,
        )
        async with asyncio.timeout(10):
            async for _ in service.control(a_request(), claimant, []):
                pass
        assert clock.now - opened == span
        assert hosts.reads[-1] - hosts.reads[0] == span
