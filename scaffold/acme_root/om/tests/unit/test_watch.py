"""The watch over memory. A live-read handle reads only the session it was
issued for, expires, and a reader resumes after the part it last saw. The
stream service's buffer per open stream is bounded, and losing it loses no
record. Under take control the agent writes nothing, and every command the
person runs is `exec` work on the host that holds the workspace, recorded
as a run attributed to them."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from contracts.loops import ASSISTANT, Clock, loop_over, reply, said, use
from pydantic import SecretStr

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.streams import StreamBounds
from acme.infra.streams.memory import StreamsMemoryImpl
from acme.infra.topics.memory import TopicsMemoryImpl
from acme.infra.transports import CommandSpec, RecordSeal, StaleCommand
from acme.infra.transports.twin import TransportTwinImpl, TwinReply
from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec, Workspace
from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.agents.impl.sink import StreamSinkMemoryImpl
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id, utcnow
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    RequestContext,
    Role,
    TenantContext,
    build_context,
)
from acme.om.events import EventsManagerInterface
from acme.om.exceptions import NotAuthorized, NotFound, StaleWriter
from acme.om.hosts.impl.manager import HostsOptions
from acme.om.hosts.types.host import Advertisement, Enrollment, HostIdentity
from acme.om.hosts.types.host import IsolationMode as Mode
from acme.om.hosts.types.pool import HostPool
from acme.om.placement.types.work import ExecPayload
from acme.om.relay.exceptions import StaleExec
from acme.om.relay.impl.manager import RelayOptions
from acme.om.relay.impl.transport import TransportRelayImpl
from acme.om.relay.types.exec import (
    ExecCall,
    ExecOutcome,
    ExecOutput,
    ExecResult,
    ExecState,
    RunRequest,
    StopKind,
)
from acme.om.retention.crossing import CrossingKind, declared
from acme.om.root import Managers, build_managers
from acme.om.steps.rules import message_step
from acme.om.steps.types.header import InputHeader, ParkReason
from acme.om.steps.types.step import StepType
from acme.om.steps.types.stream import StreamPart, TextPart
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tenancy.rules import permissions_of
from acme.om.watch.exceptions import CommandRunning, LiveReadRefused, NotHandedOver
from acme.om.watch.impl.manager import SENT, TAKEN, WatchOptions
from acme.om.watch.impl.stream import (
    COMPLETED,
    OPENED,
    PARTS,
    StreamOptions,
    StreamServiceImpl,
)
from acme.om.watch.manager import WatchManagerInterface
from acme.om.watch.root import build_watch
from acme.om.watch.rules import signed, verified, verified_item
from acme.om.watch.types.control import HandCommand
from acme.om.watch.types.live import ItemGrant, Seen

APP = AppContext(type=AppType.PORTAL, version="portal@test")
RUNNER = AppContext(type=AppType.WORKER, version="runner@test")
CONTAINER = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))
PROBED = Advertisement(os="Linux 6.8", shell="/bin/bash", isolation_modes=(Mode.CONTAINER,))
KEY = SecretStr("k" * 32)
LIFE = timedelta(minutes=5)


def request() -> RequestContext:
    return RequestContext(request_id=new_id(), app=APP)


def in_person(of: TenantContext, role: Role = Role.OWNER) -> TenantContext:
    """A member at the portal, signed in on a session of their own."""
    return build_context(
        request(),
        user_id=of.user_id if role is Role.OWNER else new_id(),
        org_id=of.org_id,
        role=role,
        permissions=permissions_of(role),
        credential_kind=CredentialKind.SESSION_TOKEN,
    )


@dataclass
class Watched:
    """One tenant's session pinned to a host that holds its workspace, an
    agent's run holding it, a stream service, and the watch over them."""

    managers: Managers
    owner: TenantContext
    person: TenantContext
    host: HostIdentity
    session_id: UUID
    epoch: int
    stream: StreamServiceImpl
    watch: WatchManagerInterface
    clock: Clock


@pytest.fixture
async def watched(tmp_path: Path) -> Watched:
    managers = build_managers(
        StorageMemoryImpl(),
        InfraLocalImpl(tmp_path),
        hosts_options=HostsOptions(claim_lease=timedelta(seconds=30)),
        relay_options=RelayOptions(lease=timedelta(seconds=30)),
    )
    owner, _ = await managers.tenancy.bootstrap(request(), "Ajax", "ajax", "ann@ajax.test", "Ann")
    now = utcnow()
    pool = await managers.hosts.create_pool(
        owner,
        HostPool(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=owner.user_id,
            updated_by=owner.user_id,
            name="build",
            region="eu-west",
        ),
    )
    issued = await managers.hosts.issue_enrollment_token(owner, pool.id)
    credential = await managers.hosts.enroll(
        request(), issued.token, Enrollment(name="host-1", advertisement=PROBED, exec_version=1)
    )
    host = await managers.hosts.authenticate(request(), credential.credential)
    session = await managers.agent_sessions.create_session(owner, make_session())
    await managers.hosts.place_session(owner, session.id, pool.id)
    await managers.relay.bind_workspace(owner, session.id, host.host_id, "/srv/work/session")
    await managers.workspaces.pinned(owner, session.id, CONTAINER)
    epoch = await managers.steps.begin_run(owner, session.id)
    clock = Clock()
    infra = InfraLocalImpl(tmp_path / "streams")
    stream = StreamServiceImpl(
        StreamsMemoryImpl(clock), infra.get_topics(), lambda: managers.events, EACH_PART
    )
    watch = build_watch(managers, stream, WatchOptions(live_read_key=KEY), clock=clock)
    return Watched(managers, owner, in_person(owner), host, session.id, epoch, stream, watch, clock)


async def _nothing(data: bytes) -> bytes | None:
    return None


NO_SEAL = RecordSeal(seal=_nothing, open=_nothing)


def text(session_id: UUID, step_id: UUID, n: int, words: str = "word ") -> TextPart:
    return TextPart(session_id=session_id, step_id=step_id, n=n, index=0, text=words)


EACH_PART = StreamOptions(window=timedelta(0))
"""A service that writes each part as it comes, for a suite of what a
stream holds part by part."""


def no_events() -> EventsManagerInterface:
    raise AssertionError("only parts are written: no event is")


def service(options: StreamOptions | None = None, clock: Clock | None = None) -> StreamServiceImpl:
    """A stream service over the memory streams, as a local root builds it."""
    streams = StreamsMemoryImpl() if clock is None else StreamsMemoryImpl(clock)
    return StreamServiceImpl(streams, TopicsMemoryImpl(), no_events, options or EACH_PART)


# Check 1: a live-read handle reads only its own session's stream, expires,
# and a reader resumes from the part it last saw.


async def test_a_live_read_reads_its_own_session_and_resumes_after_the_last_part_seen(
    watched: Watched,
) -> None:
    other = await watched.managers.agent_sessions.create_session(watched.owner, make_session())
    mine, theirs = new_id(), new_id()
    for n in range(3):
        watched.stream.emit(text(watched.session_id, mine, n))
        watched.stream.emit(text(other.id, theirs, n))
    # A part that names this session's stream from another session is not
    # its own, and no read of this session finds it.
    watched.stream.emit(text(other.id, mine, 3))
    await watched.stream.flush()
    live = await watched.watch.open_live(watched.person, watched.session_id)

    page = await watched.watch.read_live(request(), live.handle, ())
    (stream,) = page.streams
    assert (page.session_id, stream.step_id) == (watched.session_id, mine)
    assert [part.n for part in stream.parts] == [0, 1, 2] and not stream.dropped

    watched.stream.emit(text(watched.session_id, mine, 3))
    watched.stream.emit(text(watched.session_id, mine, 4))
    await watched.stream.flush()
    page = await watched.watch.read_live(request(), live.handle, (Seen(step_id=mine, n=2),))
    assert [part.n for part in page.streams[0].parts] == [3, 4]

    # The handle names its session under the platform's signature: one made
    # for another session without the key, or by another key, reads nothing.
    grant = verified(KEY.get_secret_value().encode(), live.handle)
    assert grant is not None and grant.session_id == watched.session_id
    forged_body = signed(b"x" * 32, grant.model_copy(update={"session_id": other.id})).split(".")[0]
    for handle in (
        f"{forged_body}.{live.handle.split('.')[1]}",
        signed(b"x" * 32, grant),
        live.handle + "A",
        "no handle at all",
    ):
        with pytest.raises(LiveReadRefused):
            await watched.watch.read_live(request(), handle, ())


async def test_a_sessions_handle_and_an_items_are_signed_for_purposes_of_their_own(
    watched: Watched,
) -> None:
    key = KEY.get_secret_value().encode()
    live = await watched.watch.open_live(watched.person, watched.session_id)
    item = signed(
        key,
        ItemGrant(
            item_id=watched.session_id,
            kind="frames",
            viewer_id=watched.person.user_id,
            expires_at=live.expires_at,
        ),
    )
    assert verified_item(key, live.handle) is None and verified(key, item) is None
    with pytest.raises(LiveReadRefused):
        await watched.watch.read_item_live(request(), live.handle, ())
    with pytest.raises(LiveReadRefused):
        await watched.watch.read_live(request(), item, ())


async def test_a_live_read_handle_is_issued_only_for_a_session_the_viewer_sees(
    watched: Watched,
) -> None:
    stranger, _ = await watched.managers.tenancy.bootstrap(
        request(), "Brine", "brine", "bo@brine.test", "Bo"
    )
    with pytest.raises(NotFound):
        await watched.watch.open_live(in_person(stranger), watched.session_id)


async def test_a_live_read_handle_expires(watched: Watched) -> None:
    step = new_id()
    watched.stream.emit(text(watched.session_id, step, 0))
    await watched.stream.flush()
    live = await watched.watch.open_live(watched.person, watched.session_id)
    assert live.expires_at == watched.clock.now + LIFE
    assert (await watched.watch.read_live(request(), live.handle, ())).streams
    watched.clock.now = live.expires_at
    with pytest.raises(LiveReadRefused):
        await watched.watch.read_live(request(), live.handle, ())


# Check 2: the stream service's buffer per open stream is bounded, and losing
# it loses no record.


async def test_each_open_stream_is_bounded_and_a_slow_reader_loses_the_oldest() -> None:
    clock = Clock()
    session, step, big = new_id(), new_id(), new_id()
    size = len(PARTS.dump_json(text(session, big, 0, "x" * 100), exclude_none=True))
    options = StreamOptions(
        max_parts=4, max_bytes=size * 5 // 2, max_streams=2, max_open=3, window=timedelta(0)
    )
    stream = service(options, clock)
    for n in range(10):
        stream.emit(text(session, step, n))
    await stream.flush()
    (live,) = await stream.read(session, (Seen(step_id=step, n=3),))
    assert [part.n for part in live.parts] == [6, 7, 8, 9] and live.first == 6 and live.dropped

    # By bytes: the newest part always stays.
    for n in range(4):
        stream.emit(text(session, big, n, "x" * 100))
    await stream.flush()
    held = {s.step_id: s for s in await stream.read(session, ())}
    assert [part.n for part in held[big].parts] == [2, 3]

    # By streams: a session's third, and the platform's fourth, closes the
    # stream that heard nothing longest.
    stream.emit(text(session, new_id(), 0))
    await stream.flush()
    assert step not in {s.step_id for s in await stream.read(session, ())}
    elsewhere = new_id()
    stream.emit(text(elsewhere, new_id(), 0))
    stream.emit(text(elsewhere, new_id(), 0))
    await stream.flush()
    assert len(await stream.read(session, ())) + len(await stream.read(elsewhere, ())) == 3

    # A part sent again lands once; a stream that hears nothing closes.
    last = new_id()
    stream.emit(text(elsewhere, last, 0))
    stream.emit(text(elsewhere, last, 0))
    await stream.flush()
    assert [len(s.parts) for s in await stream.read(elsewhere, ()) if s.step_id == last] == [1]
    clock.now += StreamOptions().idle
    assert await stream.read(session, ()) == () and await stream.read(elsewhere, ()) == ()


class Counted(StreamsMemoryImpl):
    """The memory streams, keeping when each stream was appended to."""

    def __init__(self) -> None:
        super().__init__()
        self.appends: dict[UUID, list[float]] = {}

    async def append(
        self, group: UUID, stream: UUID, entries: Sequence[tuple[int, bytes]], bounds: StreamBounds
    ) -> None:
        self.appends.setdefault(stream, []).append(asyncio.get_running_loop().time())
        await super().append(group, stream, entries, bounds)


async def test_a_part_at_a_time_is_written_at_most_once_a_window_and_joins_back_whole() -> None:
    """Two streams written a part at a time, a block each half: the cache
    sees at most one write a window a stream, and a reader that keeps up,
    resuming after each part's `last`, reads every block's text exactly and
    is never told of a loss."""
    window = timedelta(milliseconds=40)
    streams = Counted()
    stream = StreamServiceImpl(streams, TopicsMemoryImpl(), no_events, StreamOptions(window=window))
    session, steps = new_id(), (new_id(), new_id())
    words = [f"w{n} " for n in range(120)]
    marks: dict[UUID, int] = {}
    read: dict[tuple[UUID, int], str] = {}

    async def keep_up() -> None:
        seen = tuple(Seen(step_id=step, n=n) for step, n in marks.items())
        for live in await stream.read(session, seen):
            assert not live.dropped, "a reader that keeps up loses nothing"
            for part in live.parts:
                assert isinstance(part, TextPart)
                read[live.step_id, part.index] = (
                    read.get((live.step_id, part.index), "") + part.text
                )
                marks[live.step_id] = part.end

    loop = asyncio.get_running_loop()
    began = loop.time()
    for n, word in enumerate(words):
        for step in steps:
            stream.emit(TextPart(session_id=session, step_id=step, n=n, index=n // 60, text=word))
        await asyncio.sleep(0.002)
        await keep_up()
    took = loop.time() - began
    await stream.flush()
    await keep_up()

    for step in steps:
        assert (read[step, 0], read[step, 1]) == ("".join(words[:60]), "".join(words[60:]))
        # A window's write, the new block's, and the one `flush` makes.
        assert len(streams.appends[step]) <= took / window.total_seconds() + 3
        assert len(streams.appends[step]) < len(words) / 4
    await stream.close()


async def test_a_reader_resumes_after_a_joined_parts_last_and_hears_of_real_loss() -> None:
    """A stream that holds one entry: a joined part goes whole once the next
    lands, and a reader that read it resumes with no loss, while one that
    read less is told."""
    stream = service(StreamOptions(max_parts=1, window=timedelta(minutes=1)))
    session, step = new_id(), new_id()
    for n in range(5):
        stream.emit(text(session, step, n, f"w{n} "))
    await stream.flush()
    (live,) = await stream.read(session, (Seen(step_id=step, n=0),))
    (joined,) = live.parts
    assert (joined.n, joined.last, joined.text) == (1, 4, "w1 w2 w3 w4 ")

    for n in range(5, 8):
        stream.emit(text(session, step, n, f"w{n} "))
    await stream.flush()
    (live,) = await stream.read(session, (Seen(step_id=step, n=joined.end),))
    assert [(part.n, part.end) for part in live.parts] == [(5, 7)] and not live.dropped
    (behind,) = await stream.read(session, (Seen(step_id=step, n=0),))
    assert behind.first == 5 and behind.dropped, "the reader that never read 1 to 4 is told"
    await stream.close()


class Told(StreamSinkMemoryImpl):
    """A memory sink that also keeps when each stream opened and completed,
    in order with the parts, and hands each on to `then` when it is set."""

    def __init__(self) -> None:
        super().__init__()
        self.told: list[tuple[str, UUID]] = []
        self.then: StreamServiceImpl | None = None

    def emit(self, part: StreamPart) -> None:
        super().emit(part)
        self.told.append(("part", part.step_id))
        if self.then is not None:
            self.then.emit(part)

    def opened(self, ctx: TenantContext, session_id: UUID, step_id: UUID) -> None:
        self.told.append((OPENED, step_id))
        if self.then is not None:
            self.then.opened(ctx, session_id, step_id)

    def completed(self, ctx: TenantContext, session_id: UUID, step_id: UUID) -> None:
        self.told.append((COMPLETED, step_id))
        if self.then is not None:
            self.then.completed(ctx, session_id, step_id)


async def test_a_stream_holds_its_cap_and_once_it_is_gone_its_step_is_whole(
    tmp_path: Path,
) -> None:
    told = Told()
    loop = loop_over(tmp_path, sink=told)
    session_id = await loop.start()
    await loop.say(session_id, "What is the total?")
    answer = "The total is twelve, as the records of the last quarter show it."
    loop.anthropic.add(reply(said(answer)))
    await loop.loops.run(loop.owner, session_id)
    steps = await loop.history(session_id)
    (response,) = [step for step in steps if step.type is StepType.MODEL_RESPONSE]
    # The loop opens the response's stream before its first part, and
    # completes it after its last.
    assert told.told[0] == (OPENED, response.id) and told.told[-1] == (COMPLETED, response.id)
    assert {kind for kind, _ in told.told[1:-1]} == {"part"} and len(told.parts) > 2

    stream = StreamServiceImpl(
        StreamsMemoryImpl(),
        loop.infra.get_topics(),
        lambda: loop.managers.events,
        StreamOptions(max_parts=2, window=timedelta(0)),
    )
    stream.opened(loop.owner, session_id, response.id)
    for part in told.parts:
        stream.emit(part)
    await stream.flush()
    (live,) = await stream.read(session_id, ())
    assert len(live.parts) == 2 and live.dropped, "the stream let go of the oldest parts"

    stream.completed(loop.owner, session_id, response.id)
    await stream.flush()
    assert await stream.read(session_id, ()) == (), "a completed stream is gone"
    assert response.id == live.step_id and response.as_text() == answer
    events = await loop.managers.events.get_events(loop.owner, 0, 200)
    changes = [
        (e.kind, e.target_id, e.payload["step_id"])
        for e in events
        if e.kind.startswith("watch.stream.")
    ]
    assert changes == [
        (OPENED, session_id, str(response.id)),
        (COMPLETED, session_id, str(response.id)),
    ]


async def test_a_tools_output_stream_opens_completes_and_is_gone_once_its_step_is_stored(
    tmp_path: Path,
) -> None:
    told = Told()
    worked = ASSISTANT.model_copy(
        update={
            "name": "worked",
            "isolation": IsolationSpec(
                mode=IsolationMode.TWIN, egress=EgressPolicy(mode=EgressMode.NONE)
            ),
        }
    )
    loop = loop_over(tmp_path, sink=told, kinds=(worked,))
    told.then = stream = StreamServiceImpl(
        StreamsMemoryImpl(), loop.infra.get_topics(), lambda: loop.managers.events
    )
    transport = loop.infra.get_transport()
    assert isinstance(transport, TransportTwinImpl)

    async def printing(command: CommandSpec, env: Mapping[str, str]) -> TwinReply:
        return TwinReply(stdout="counted twelve\n")

    transport.handler = printing
    loop.tools["lookup"].argv = ("count",)
    session_id = await loop.start("worked")
    await loop.say(session_id, "How many are there?")
    loop.anthropic.add(reply(use("lookup")))
    loop.anthropic.add(reply(said("Twelve.")))
    await loop.loops.run(loop.owner, session_id)
    (answer,) = [s for s in await loop.history(session_id) if s.type is StepType.TOOL_RESPONSE]

    # The call's output streams under its response: opened before it runs,
    # completed after the response is stored.
    assert [kind for kind, step_id in told.told if step_id == answer.id] == [
        OPENED,
        "part",
        COMPLETED,
    ]
    await stream.flush()
    assert await stream.read(session_id, ()) == (), "every stream of the run is gone"
    events = await loop.managers.events.get_events(loop.owner, 0, 200)
    hints = [
        (e.kind, e.target_id)
        for e in events
        if e.kind.startswith("watch.stream.") and e.payload["step_id"] == str(answer.id)
    ]
    assert hints == [(OPENED, session_id), (COMPLETED, session_id)]


# Check 4: under take control the agent writes nothing, and every command the
# person runs is a recorded run attributed to them, as `exec` work on the
# host that holds the workspace.


async def claim(watched: Watched) -> ExecPayload | None:
    for _ in range(50):
        claimed = await watched.managers.hosts.claim(request(), watched.host, 1)
        if claimed is not None:
            return ExecPayload.model_validate(claimed[1].payload)
        await asyncio.sleep(0.002)
    return None


async def finish(watched: Watched, payload: ExecPayload, stdout: str) -> None:
    result = ExecResult(outcome=ExecOutcome(exit_code=0), output=ExecOutput(stdout=stdout))
    data = result.model_dump_json().encode()
    await watched.managers.relay.push_result(
        request(), watched.host, payload.item_id, declared(CrossingKind.RESULT, data), data
    )


async def test_under_take_control_the_agent_writes_nothing(watched: Watched) -> None:
    taken = await watched.watch.take_control(watched.person, watched.session_id)
    assert taken.park is not None and taken.park.reason is ParkReason.HANDOVER
    before = await watched.managers.steps.get_cursor(watched.owner, watched.session_id)

    # The run that held the loop is fenced in the history and in the wall.
    note = message_step(new_id(), utcnow(), watched.session_id, watched.owner, "still working")
    with pytest.raises(StaleWriter):
        await watched.managers.steps.append_steps(
            watched.owner, watched.session_id, watched.epoch, [note]
        )
    transport = TransportRelayImpl(
        lambda: watched.managers.relay, lambda: RequestContext(request_id=new_id(), app=RUNNER)
    )
    workspace = Workspace(
        id=watched.session_id, org_id=watched.owner.org_id, spec=CONTAINER, location=""
    )
    agents = CommandSpec(
        argv=("git", "push"),
        key=new_id(),
        epoch=watched.epoch,
        deadline=utcnow() + timedelta(seconds=30),
        effect="unsafe",
    )
    with pytest.raises(StaleCommand):
        await transport.run(workspace, agents, seal=NO_SEAL)
    # A run woken while it is handed over takes nothing up.
    woken = await watched.managers.loop.run(watched.owner, watched.session_id)
    assert woken.end is RunEnd.IDLE
    after = await watched.managers.steps.get_cursor(watched.owner, watched.session_id)
    assert after.head == before.head, "the agent appended nothing"
    assert await claim(watched) is None, "no command of the agent's reached the host"


async def test_every_command_by_hand_is_a_recorded_run_attributed_to_the_person(
    watched: Watched,
) -> None:
    command = HandCommand(key=new_id(), argv=("make", "test"))
    with pytest.raises(NotHandedOver):
        await watched.watch.run_command(watched.person, watched.session_id, command)

    await watched.watch.take_control(watched.person, watched.session_id)
    run = await watched.watch.run_command(watched.person, watched.session_id, command)
    assert (run.user_id, run.key, run.state) == (
        watched.person.user_id,
        command.key,
        ExecState.QUEUED,
    )
    again = await watched.watch.run_command(watched.person, watched.session_id, command)
    assert again.item_id == run.item_id, "the same key is the same run"

    payload = await claim(watched)
    assert payload is not None and payload.item_id == run.item_id
    assert payload.by_person, "the host's owner reads it as a person's command"
    detail = await watched.managers.relay.detail(request(), watched.host, run.item_id)
    assert detail.request == RunRequest(argv=("make", "test"))
    assert (detail.epoch, detail.spec) == (run.epoch, CONTAINER)
    await finish(watched, payload, "12 passed\n")

    ended = await watched.watch.command(watched.person, watched.session_id, command.key, -1)
    assert ended.state is ExecState.DONE and ended.outcome is not None
    assert ended.outcome.exit_code == 0 and ended.output is not None
    assert ended.output.stdout == "12 passed\n"

    events = await watched.managers.events.get_events(watched.owner, 0, 100)
    (sent,) = [event for event in events if event.kind == SENT]
    assert (sent.actor_id, sent.target_id) == (watched.person.user_id, run.item_id)
    (taken,) = [event for event in events if event.kind == TAKEN]
    assert taken.actor_id == watched.person.user_id


async def test_giving_back_hands_over_the_summary_and_fences_a_command_no_host_took(
    watched: Watched,
) -> None:
    await watched.watch.take_control(watched.person, watched.session_id)
    pending = HandCommand(key=new_id(), argv=("make", "clean"))
    await watched.watch.run_command(watched.person, watched.session_id, pending)

    back = await watched.watch.give_back(
        watched.person, watched.session_id, "I fixed the checkout config by hand."
    )
    assert back.park is None and back.status is not SessionStatus.PARKED
    steps = await watched.managers.steps.get_steps(watched.owner, watched.session_id, 0, 100)
    (summary,) = [s for s in steps.items if s.type is StepType.MESSAGE]
    assert summary.as_text() == "I fixed the checkout config by hand."
    assert isinstance(summary.header, InputHeader)
    assert summary.header.principal is not None
    assert summary.header.principal.id == watched.person.user_id

    assert await claim(watched) is None, "a command no host took never runs after the giving back"
    ended = await watched.watch.command(watched.person, watched.session_id, pending.key, -1)
    assert ended.state is ExecState.INTERRUPTED and ended.outcome is not None
    assert ended.outcome.refused == StaleExec.code
    with pytest.raises(NotHandedOver):
        await watched.watch.run_command(
            watched.person, watched.session_id, HandCommand(key=new_id(), argv=("ls",))
        )


async def test_take_control_stops_what_the_agent_still_runs_on_the_host(
    watched: Watched,
) -> None:
    call = ExecCall(
        session_id=watched.session_id,
        key=new_id(),
        request=RunRequest(argv=("make", "deploy")),
        effect="unsafe",
        deadline=utcnow() + timedelta(seconds=30),
        epoch=watched.epoch,
        spec=CONTAINER,
    )
    agents = await watched.managers.relay.send(request(), watched.owner.org_id, call, 0)
    payload = await claim(watched)
    assert payload is not None and payload.item_id == agents.id and not payload.by_person
    (running,) = await watched.managers.relay.running(
        request(), watched.owner.org_id, watched.session_id
    )
    assert running.id == agents.id

    await watched.watch.take_control(watched.person, watched.session_id)
    progress = await watched.managers.relay.watch(request(), watched.owner.org_id, agents.id, -1)
    assert progress.state is ExecState.INTERRUPTED and progress.outcome is not None
    assert progress.outcome.stopped is StopKind.INTERRUPT
    controls = await watched.managers.relay.controls(request(), watched.host, None)
    assert [(c.item_id, c.kind) for c in controls] == [(agents.id, StopKind.REVOKE)], (
        "its host is told to end it and push nothing"
    )
    with pytest.raises(Exception, match="not held"):
        await finish(watched, payload, "deployed\n")


async def test_giving_back_while_a_command_by_hand_runs_is_refused_unless_it_is_stopped(
    watched: Watched,
) -> None:
    await watched.watch.take_control(watched.person, watched.session_id)
    command = HandCommand(key=new_id(), argv=("make", "flash"))
    run = await watched.watch.run_command(watched.person, watched.session_id, command)
    assert await claim(watched) is not None

    with pytest.raises(CommandRunning):
        await watched.watch.give_back(watched.person, watched.session_id, "Flashed it.")
    session = await watched.managers.agent_sessions.get_session(watched.owner, watched.session_id)
    assert session.park is not None and session.park.reason is ParkReason.HANDOVER

    back = await watched.watch.give_back(
        watched.person, watched.session_id, "Flashed it.", stop=True
    )
    assert back.park is None
    ended = await watched.watch.command(watched.person, watched.session_id, command.key, -1)
    assert ended.state is ExecState.INTERRUPTED and ended.outcome is not None
    assert ended.outcome.stopped is StopKind.INTERRUPT
    controls = await watched.managers.relay.controls(request(), watched.host, None)
    assert [(c.item_id, c.kind) for c in controls] == [(run.item_id, StopKind.REVOKE)]


async def test_control_is_taken_by_a_person_in_person_who_may_instruct(
    watched: Watched,
) -> None:
    agents_call = watched.owner  # an internal context, as an agent's call runs under
    viewer = in_person(watched.owner, Role.VIEWER)
    for ctx in (agents_call, viewer):
        with pytest.raises(NotAuthorized):
            await watched.watch.take_control(ctx, watched.session_id)
    session = await watched.managers.agent_sessions.get_session(watched.owner, watched.session_id)
    assert session.park is None
