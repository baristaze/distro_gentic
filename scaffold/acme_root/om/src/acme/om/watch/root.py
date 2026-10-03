"""The watch swimlane over the engine's managers, as a root builds it.

    stream = StreamServiceMemoryImpl()
    watch = build_watch(managers, stream, WatchOptions(live_read_key=key))

`stream` is the stream service the reads come from. A root that runs the
loop could hand it the same service as its `stream_sink`; none does yet,
so a read finds nothing open."""

from collections.abc import Callable
from datetime import datetime

from acme.om.base import utcnow
from acme.om.root import Managers
from acme.om.watch.impl.manager import WatchManagerImpl, WatchOptions
from acme.om.watch.manager import WatchManagerInterface
from acme.om.watch.stream import StreamServiceInterface


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
