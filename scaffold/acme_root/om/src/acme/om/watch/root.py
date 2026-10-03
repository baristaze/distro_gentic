"""The watch swimlane over the engine's managers, as a root builds it.

    stream = build_stream(infra, lambda: managers.events)
    kinds = build_kind_streams(infra, product_kinds)
    watch = build_watch(managers, stream, WatchOptions(live_read_key=key), kind_streams=kinds)

A product's stream kinds are registered beside the step's, passed to
`build_stream` as `product_kinds`, and `build_kind_streams` writes
and reads them. The watch reads and writes, through it, the kinds a
product's claimant writes for the item it holds.

`stream` is the stream service over infra's streams, the shared cache's:
the session runner hands it to the loop as its `stream_sink`, building it
before the managers, and the API's watch reads it, so a read in one process
finds the streams the runner writes in another."""

from collections.abc import Callable
from datetime import datetime

from acme.infra.root import InfraInterface
from acme.om.base import utcnow
from acme.om.events import EventsManagerInterface
from acme.om.root import Managers, ProductKinds
from acme.om.watch.impl.kinds import KindStreamsImpl
from acme.om.watch.impl.manager import WatchManagerImpl, WatchOptions
from acme.om.watch.impl.stream import StreamOptions, StreamServiceImpl, step_kinds
from acme.om.watch.kinds import KindStreamsInterface
from acme.om.watch.manager import WatchManagerInterface
from acme.om.watch.stream import StreamServiceInterface


def build_stream(
    infra: InfraInterface,
    events: Callable[[], EventsManagerInterface],
    options: StreamOptions | None = None,
    product_kinds: ProductKinds | None = None,
) -> StreamServiceInterface:
    """`events` is read when a stream opens or completes, so a root that runs
    the loop passes the managers it is about to build. The step's bounds
    are `options`', registered beside a product's stream kinds."""
    options = options or StreamOptions()
    registry = step_kinds(options, *(product_kinds or ProductKinds()).streams)
    return StreamServiceImpl(infra.get_streams(), infra.get_topics(), events, options, registry)


def build_kind_streams(
    infra: InfraInterface, product_kinds: ProductKinds, options: StreamOptions | None = None
) -> KindStreamsInterface:
    """The live streams of a product's stream kinds, each under its own
    bounds, on the cache the step's parts share."""
    registry = step_kinds(options or StreamOptions(), *product_kinds.streams)
    return KindStreamsImpl(infra.get_streams(), registry)


def build_watch(
    managers: Managers,
    stream: StreamServiceInterface,
    options: WatchOptions | None = None,
    *,
    kind_streams: KindStreamsInterface | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> WatchManagerInterface:
    """`kind_streams` are a product's, which its claimants write for the
    items they hold; with none, every such stream is not found."""
    return WatchManagerImpl(
        managers.agent_sessions,
        managers.agents,
        managers.loop,
        managers.steps,
        managers.relay,
        managers.workspaces,
        managers.events,
        stream,
        options or WatchOptions(),
        clock,
        hosts=managers.hosts,
        work=managers.work,
        kind_streams=kind_streams,
    )
