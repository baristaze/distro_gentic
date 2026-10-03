"""The watch swimlane over the engine's managers, as a root builds it.

    stream = build_stream(infra, lambda: managers.events)
    watch = build_watch(managers, stream, WatchOptions(live_read_key=key))

`stream` is the stream service over infra's streams, the shared cache's:
the session runner hands it to the loop as its `stream_sink`, building it
before the managers, and the API's watch reads it, so a read in one process
finds the streams the runner writes in another."""

from collections.abc import Callable
from datetime import datetime

from acme.infra.root import InfraInterface
from acme.om.base import utcnow
from acme.om.events import EventsManagerInterface
from acme.om.root import Managers
from acme.om.watch.impl.manager import WatchManagerImpl, WatchOptions
from acme.om.watch.impl.stream import StreamOptions, StreamServiceImpl
from acme.om.watch.manager import WatchManagerInterface
from acme.om.watch.stream import StreamServiceInterface


def build_stream(
    infra: InfraInterface,
    events: Callable[[], EventsManagerInterface],
    options: StreamOptions | None = None,
) -> StreamServiceInterface:
    """`events` is read when a stream opens or completes, so a root that runs
    the loop passes the managers it is about to build."""
    return StreamServiceImpl(infra.get_streams(), infra.get_topics(), events, options)


def build_watch(
    managers: Managers,
    stream: StreamServiceInterface,
    options: WatchOptions | None = None,
    *,
    clock: Callable[[], datetime] = utcnow,
) -> WatchManagerInterface:
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
    )
