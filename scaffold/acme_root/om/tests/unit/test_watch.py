"""The watch over memory. A live-read handle reads only the session it was
issued for, expires, and a reader resumes after the part it last saw. The
stream service's buffer per open stream is bounded, and losing it loses no
record. Under take control the agent writes nothing, and every command the
person runs is `exec` work on the host that holds the workspace, recorded
as a run attributed to them."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from contracts.loops import Clock, loop_over, reply, said
from pydantic import SecretStr

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.transports import CommandSpec, RecordSeal, StaleCommand
from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec, Workspace
from acme.om.agent_sessions.types.agent_session import SessionStatus
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
    ExecOutcome,
    ExecOutput,
    ExecResult,
    ExecState,
    RunRequest,
)
from acme.om.retention.crossing import CrossingKind, declared
from acme.om.root import Managers, build_managers
from acme.om.steps.rules import message_step
from acme.om.steps.types.header import InputHeader, ParkReason
from acme.om.steps.types.step import StepType
from acme.om.steps.types.stream import TextPart
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tenancy.rules import permissions_of
from acme.om.watch.exceptions import LiveReadRefused, NotHandedOver
from acme.om.watch.impl.manager import SENT, TAKEN, WatchOptions
from acme.om.watch.impl.stream import StreamOptions, StreamServiceMemoryImpl
from acme.om.watch.manager import WatchManagerInterface
from acme.om.watch.root import build_watch
from acme.om.watch.rules import signed, verified
from acme.om.watch.types.control import HandCommand
from acme.om.watch.types.live import Seen

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
    stream: StreamServiceMemoryImpl
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
            name="lab",
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
    stream = StreamServiceMemoryImpl(clock=clock)
    watch = build_watch(managers, stream, WatchOptions(live_read_key=KEY), clock=clock)
    return Watched(managers, owner, in_person(owner), host, session.id, epoch, stream, watch, clock)


async def _nothing(data: bytes) -> bytes | None:
    return None


NO_SEAL = RecordSeal(seal=_nothing, open=_nothing)


def text(session_id: UUID, step_id: UUID, n: int, words: str = "word ") -> TextPart:
    return TextPart(session_id=session_id, step_id=step_id, n=n, index=0, text=words)


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
    live = await watched.watch.open_live(watched.person, watched.session_id)

    page = await watched.watch.read_live(request(), live.handle, ())
    (stream,) = page.streams
    assert (page.session_id, stream.step_id) == (watched.session_id, mine)
    assert [part.n for part in stream.parts] == [0, 1, 2] and not stream.dropped

    watched.stream.emit(text(watched.session_id, mine, 3))
    watched.stream.emit(text(watched.session_id, mine, 4))
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
    live = await watched.watch.open_live(watched.person, watched.session_id)
    assert live.expires_at == watched.clock.now + LIFE
    assert (await watched.watch.read_live(request(), live.handle, ())).streams
    watched.clock.now = live.expires_at
    with pytest.raises(LiveReadRefused):
        await watched.watch.read_live(request(), live.handle, ())


# Check 2: the stream service's buffer per open stream is bounded, and losing
# it loses no record.


def test_each_open_stream_is_bounded_and_a_slow_reader_loses_the_oldest() -> None:
    clock = Clock()
    options = StreamOptions(max_parts=4, max_bytes=250, max_streams=2, max_open=3)
    stream = StreamServiceMemoryImpl(options, clock)
    session, step = new_id(), new_id()
    for n in range(10):
        stream.emit(text(session, step, n))
    (live,) = stream.read(session, (Seen(step_id=step, n=3),))
    assert [part.n for part in live.parts] == [6, 7, 8, 9] and live.first == 6 and live.dropped

    # By bytes: the newest part always stays.
    big = new_id()
    for n in range(4):
        stream.emit(text(session, big, n, "x" * 100))
    held = {s.step_id: s for s in stream.read(session, ())}
    assert [part.n for part in held[big].parts] == [2, 3]

    # By streams: a session's third, and the platform's fourth, closes the
    # stream that heard nothing longest.
    stream.emit(text(session, new_id(), 0))
    assert step not in {s.step_id for s in stream.read(session, ())}
    elsewhere = new_id()
    stream.emit(text(elsewhere, new_id(), 0))
    stream.emit(text(elsewhere, new_id(), 0))
    assert len(stream.read(session, ())) + len(stream.read(elsewhere, ())) == 3

    # A part sent again lands once; a stream that hears nothing closes.
    last = new_id()
    stream.emit(text(elsewhere, last, 0))
    stream.emit(text(elsewhere, last, 0))
    assert [len(s.parts) for s in stream.read(elsewhere, ()) if s.step_id == last] == [1]
    clock.now += StreamOptions().idle
    assert stream.read(session, ()) == () and stream.read(elsewhere, ()) == ()


async def test_losing_the_buffer_loses_no_record(tmp_path: Path) -> None:
    loop = loop_over(tmp_path)
    session_id = await loop.start()
    await loop.say(session_id, "What is the total?")
    answer = "The total is twelve, as the records of the last quarter show it."
    loop.anthropic.add(reply(said(answer)))
    await loop.loops.run(loop.owner, session_id)

    stream = StreamServiceMemoryImpl(StreamOptions(max_parts=2))
    for part in loop.sink.parts:
        stream.emit(part)
    (live,) = stream.read(session_id, ())
    assert len(live.parts) == 2 and live.dropped, "the buffer let go of the oldest parts"

    lost = StreamServiceMemoryImpl()  # the service restarted: every buffer gone
    assert lost.read(session_id, ()) == ()
    steps = await loop.history(session_id)
    (response,) = [step for step in steps if step.type is StepType.MODEL_RESPONSE]
    assert response.id == live.step_id and response.as_text() == answer


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
        watched.person, watched.session_id, "I fixed the gripper config by hand."
    )
    assert back.park is None and back.status is not SessionStatus.PARKED
    steps = await watched.managers.steps.get_steps(watched.owner, watched.session_id, 0, 100)
    (summary,) = [s for s in steps.items if s.type is StepType.MESSAGE]
    assert summary.as_text() == "I fixed the gripper config by hand."
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
