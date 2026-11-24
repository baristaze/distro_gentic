"""A host runs relayed work against the live app, in process. A tool call
the runner relays runs once, on the host that holds the workspace, through
its local transport: its output streams back a window at a time and its
result lands under the call's key. A cancel or an interrupt the platform
records reaches the host over the control stream it holds open, and ends
the command at once. A host's routes take its own credential alone. A
workspace whose instance went since its host prepared it, as after a
reboot or a Docker restart, is prepared again, and its call runs."""

import asyncio
import base64
import json
import shutil
import subprocess
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from host_support import (
    DETAIL,
    Pace,
    Stack,
    Widened,
    container_host,
    directory_host,
    docker_runs,
    probes,
)
from prometheus_client import REGISTRY

from acme.apps.host import agent as host_agent
from acme.apps.host import main as host_main
from acme.apps.host.agent import HostAgent
from acme.apps.host.ceilings import Ceilings
from acme.apps.host.exec_relay import PUSH_BYTES, ExecutorRelayImpl
from acme.apps.host.mcp import HostServers
from acme.client.client import ApiClient
from acme.client.types.hosts import IsolationMode as HostMode
from acme.infra.agent_workspaces import (
    AgentWorkspace,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
)
from acme.infra.agent_workspaces.container import DEFAULT_IMAGE, AgentWorkspaceContainerImpl
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports import CapabilityMissing, CommandResult, CommandSpec, RecordSeal
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import TransportLocalImpl
from acme.om.agent_steps.types.header import ToolFailure
from acme.om.base import new_id
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    RequestContext,
    TenantContext,
    build_context,
)
from acme.om.exceptions import ToolFailed
from acme.om.exec_relay.impl.transport import TransportRelayImpl
from acme.om.exec_relay.types.exec import INLINE_BYTES, ExecState, StopKind
from acme.om.hosts.rules import USER_VERSION
from acme.om.placement.types.work import ExecPayload
from acme.om.tenancy.rules import permissions_of
from acme.om.watch.root import build_watch
from acme.om.watch.types.control import HandCommand
from acme.services.api.services.impl import exec_relay as exec_relay_service

from contracts.agent_project_storage import make_agent_project, make_binding
from contracts.agent_session_storage import make_agent_session

RUNNER = AppContext(type=AppType.WORKER, version="runner@test")
DIRECTORY = IsolationSpec(mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.NONE))
APART = "65534:65534"
"""A user apart from a workspace's own, by its id and its group's."""


async def _nothing(data: bytes) -> bytes | None:
    return None


NO_SEAL = RecordSeal(seal=_nothing, open=_nothing)


@dataclass
class Relayed:
    api: Stack
    host: HostAgent
    executor: ExecutorRelayImpl
    runner: TransportRelayImpl
    workspace: AgentWorkspace
    epoch: int
    host_id: UUID


@pytest.fixture
async def relayed(api: Stack, tmp_path: Path) -> AsyncIterator[Relayed]:
    yield await relay_to(api, tmp_path)


async def relay_to(
    api: Stack,
    tmp_path: Path,
    agent_project_id: UUID | None = None,
    serves: UUID | None = None,
    wire: httpx.AsyncBaseTransport | None = None,
    now: Callable[[], datetime] | None = None,
    flush_seconds: float = 0.0,
    servers: HostServers | None = None,
    window_chars: int = 32_000,
    readable: tuple[str, ...] | None = None,
    min_isolation: HostMode = HostMode.directory,
) -> Relayed:
    """A host of the tenant's pool that holds a session's workspace, a
    directory it runs commands in through the engine's local transport, and
    the runner's exec relay to it. With `serves`, the host's ceilings serve that
    agent project alone, and the session belongs to `agent_project_id`. With `wire`, the
    host reaches the platform through it, and with `now` it reads its time.
    It sends what a command prints at once, or `flush_seconds` apart or
    `window_chars` at a time, and starts the MCP servers `servers` names.
    Its owner names the paths it reads in `readable`, its workspace's
    directory unless named, and its minimum isolation in `min_isolation`."""
    pool = await api.pool()
    where = tmp_path / "workspace"
    where.mkdir()
    agents: list[HostAgent] = []
    executor = ExecutorRelayImpl(
        lambda: agents[0].client(),
        {
            IsolationMode.HOST: TransportLocalImpl(
                tmp_path / "records", SecretsLocalImpl(None), BrokerNullImpl()
            )
        },
        flush_seconds=flush_seconds,
        window_chars=window_chars,
        renew_seconds=0.2,
        servers=servers,
    )
    host = HostAgent(
        api.settings(tmp_path / "home", await api.token(pool.id)),
        Ceilings(
            agent_projects=None if serves is None else frozenset({serves}),
            min_isolation=min_isolation,
            egress=frozenset(),
            readable=(str(where),) if readable is None else readable,
        ),
        probes(HostMode.directory),
        lambda token: ApiClient(
            "http://test",
            app="api",
            app_version="host@test",
            token=token,
            transport=wire or api.transport,
            store_transport=api.store,
        ),
        executor,
        now=now or (lambda: datetime.now(UTC)),
    )
    agents.append(host)
    await host.start()
    managers = api.container.managers
    session = await managers.agent_sessions.create_agent_session(api.owner, make_agent_session())
    if agent_project_id is not None:
        await api.container.storage.get_agent_project_storage().bind_session(
            api.owner.org_id, make_binding(session.id, agent_project_id)
        )
    await managers.hosts.place_session(api.owner, session.id, pool.id)
    host_id = UUID(host.credential.claimant_id)
    await managers.exec_relay.bind_workspace(api.owner, session.id, host_id, str(where))
    epoch = await managers.agent_steps.begin_run(api.owner, session.id)
    workspace = AgentWorkspace(id=session.id, org_id=api.owner.org_id, spec=DIRECTORY, location="")
    return Relayed(api, host, executor, runner_of(api), workspace, epoch, host_id)


def runner_of(api: Stack) -> TransportRelayImpl:
    """The runner's exec relay to the tenant's hosts."""
    return TransportRelayImpl(
        lambda: api.container.managers.exec_relay,
        lambda: RequestContext(request_id=new_id(), app=RUNNER),
        first_poll=timedelta(milliseconds=5),
        last_poll=timedelta(milliseconds=20),
    )


async def bound_on(host: HostAgent, api: Stack, spec: IsolationSpec) -> tuple[UUID, str]:
    """A session of the host's pool whose workspace the host prepared and
    holds: its id, and where the host made it."""
    managers = api.container.managers
    session = await managers.agent_sessions.create_agent_session(api.owner, make_agent_session())
    await managers.hosts.place_session(api.owner, session.id, host_pool(host))
    await managers.exec_relay.ask_prepare(api.owner, session.id, spec)
    assert await host.claim_once() is not None
    await host.idle()
    held = await managers.exec_relay.binding_of(api.owner, session.id)
    assert held is not None
    return session.id, held.location


async def run_on(
    host: HostAgent,
    api: Stack,
    agent_session_id: UUID,
    spec: IsolationSpec,
    *argv: str,
    user: str | None = None,
) -> CommandResult:
    """A command of the session's next run, relayed to the host that holds
    its workspace, while that host claims: as `user` when it names one."""
    epoch = await api.container.managers.agent_steps.begin_run(api.owner, agent_session_id)
    workspace = AgentWorkspace(id=agent_session_id, org_id=api.owner.org_id, spec=spec, location="")
    waiting = asyncio.ensure_future(
        runner_of(api).run(workspace, command(epoch, *argv, user=user), seal=NO_SEAL)
    )
    await claims(host, waiting)
    return await waiting


def command(epoch: int, *argv: str, seconds: float = 30, user: str | None = None) -> CommandSpec:
    return CommandSpec(
        argv=argv,
        key=new_id(),
        epoch=epoch,
        deadline=datetime.now(UTC) + timedelta(seconds=seconds),
        effect="unsafe",
        user=user,
    )


async def claims(host: HostAgent, until: asyncio.Future[Any]) -> list[UUID]:
    """The host's loop while the runner waits: the exec items it was
    handed, by the exec relay's id."""
    handed: list[UUID] = []
    pace = Pace()
    while not until.done():
        one = await host.tick()
        if one is not None:
            handed.append(ExecPayload.model_validate(one.item.payload).item_id)
        await pace.after(one is not None)
    return handed


async def test_a_relayed_command_runs_once_on_its_host_and_streams_its_output(
    relayed: Relayed,
) -> None:
    printed: list[tuple[str, str]] = []

    async def sink(stream: str, text: str) -> None:
        printed.append((stream, text))

    spec = command(relayed.epoch, "sh", "-c", "echo one; sleep 0.3; echo two >&2; echo three")
    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, sink, seal=NO_SEAL))
    handed = await claims(relayed.host, waiting)
    ran = await waiting
    assert isinstance(ran, CommandResult)
    assert (ran.key, ran.exit_code, ran.stdout, ran.stderr) == (
        spec.key,
        0,
        "one\nthree\n",
        "two\n",
    )
    assert "".join(text for stream, text in printed if stream == "stdout") == "one\nthree\n"
    assert ("stderr", "two\n") in printed
    assert len(handed) == 1  # once, on the host that holds the workspace
    # The result is stored under the call's key: a resumed run reads it, and
    # nothing runs again.
    epoch = await relayed.api.container.managers.agent_steps.begin_run(
        relayed.api.owner, relayed.workspace.id
    )
    again = await relayed.runner.outcome(relayed.workspace, spec.key, epoch, seal=NO_SEAL)
    assert again is not None and again.stdout == "one\nthree\n"
    assert await relayed.host.claim_once() is None


async def test_a_relayed_read_from_an_offset_answers_only_what_follows_it(
    relayed: Relayed,
) -> None:
    wrote = command(relayed.epoch, "sh", "-c", "printf 'head,tail' > grows.log")
    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, wrote, seal=NO_SEAL))
    await claims(relayed.host, waiting)
    assert (await waiting).exit_code == 0
    reading = asyncio.ensure_future(
        relayed.runner.read_file(relayed.workspace, "grows.log", 64, offset=5)
    )
    pace = Pace()
    while not reading.done():
        await pace.after(await relayed.host.tick() is not None)
    assert await reading == b"tail"


def newer(result: dict[str, Any]) -> bool:
    """Whether a result carries what a platform of an earlier release
    refuses: times, or bytes inline."""
    inline = any("data" in (result.get(name) or {}) for name in ("output", "file"))
    return "times" in result or inline


class Crossed(httpx.AsyncBaseTransport):
    """The stack, noting the operation each `exec` item's detail hands the
    host, as its claim carries it or its own route answers it, each call
    the host makes, by its method and the end of its path, and each result
    it pushes. With `earlier`, the platform is of an earlier release: a
    claim carries no detail, a detail keeps no times and takes nothing
    inline, and a result that carries times or bytes inline is refused.
    With `rolling`, the claim and the detail are this release's, but each
    result that carries times or bytes inline reaches a replica of an
    earlier release, which refuses it."""

    def __init__(
        self, inner: httpx.AsyncBaseTransport, *, earlier: bool = False, rolling: bool = False
    ) -> None:
        self._inner = inner
        self._earlier = earlier
        self._rolling = rolling
        self.asked: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self.answered: list[dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        claims = request.method == "POST" and path == "/v1/hosts/me/claims"
        detail = request.method == "GET" and DETAIL.fullmatch(path) is not None
        self.calls.append("detail" if detail else f"{request.method} {path.rsplit('/', 1)[-1]}")
        if request.method == "POST" and path.endswith("/result"):
            pushed = json.loads(await request.aread())["data"]
            self.answered.append(json.loads(base64.b64decode(pushed)))
            if (self._earlier or self._rolling) and newer(self.answered[-1]):
                refused = {
                    "code": "validation_failed",
                    "message": "a result that is no exec result",
                }
                return httpx.Response(422, json={"error": refused})
        response = await self._inner.handle_async_request(request)
        if response.status_code != 200 or not (claims or detail):
            return response
        body = json.loads(await response.aread())
        if detail:
            self.asked.append(body["request"])
            if self._earlier:
                body.pop("times", None)
                body.pop("inline", None)
        item = body.get("item") if claims else None
        if item is not None and item.get("detail") is not None:
            if self._earlier:
                del item["detail"]
            else:
                self.asked.append(item["detail"]["request"])
        headers = [(k, v) for k, v in response.headers.raw if k.lower() != b"content-length"]
        return httpx.Response(
            response.status_code, headers=headers, content=json.dumps(body).encode()
        )


async def test_a_host_echoes_the_offset_it_read_from_and_a_read_from_the_start_carries_none(
    api: Stack, tmp_path: Path
) -> None:
    wire = Crossed(api.transport)
    relayed = await relay_to(api, tmp_path, wire=wire)
    (tmp_path / "workspace" / "grows.log").write_bytes(b"head,tail")
    for offset, rest in [(0, b"head,tail"), (5, b"tail")]:
        reading = asyncio.ensure_future(
            relayed.runner.read_file(relayed.workspace, "grows.log", 64, offset=offset)
        )
        pace = Pace()
        while not reading.done():
            await pace.after(await relayed.host.tick() is not None)
        assert await reading == rest
    # The read from the start is the item and the answer an earlier release
    # sent: neither names an offset. The read past it is echoed.
    assert [read.get("offset") for read in wire.asked] == [None, 5]
    assert [answer.get("offset") for answer in wire.answered] == [None, 5]


class Read:
    """The runner's clock, noting each time it is read."""

    def __init__(self) -> None:
        self.reads: list[datetime] = []

    def __call__(self) -> datetime:
        now = datetime.now(UTC)
        self.reads.append(now)
        return now


PHASES = ("queued", "detail", "start", "command", "store", "read")


def observed(operation: str) -> dict[str, tuple[float, float]]:
    """How many observations of each phase of `operation`, and of its
    overhead, the runner's metrics hold, and their sum."""

    def sample(name: str, labels: dict[str, str]) -> tuple[float, float]:
        count = REGISTRY.get_sample_value(f"{name}_count", labels) or 0.0
        return count, REGISTRY.get_sample_value(f"{name}_sum", labels) or 0.0

    held = {
        phase: sample("acme_exec_relay_phase_seconds", {"phase": phase, "operation": operation})
        for phase in PHASES
    }
    held["overhead"] = sample("acme_exec_relay_overhead_seconds", {"operation": operation})
    return held


async def test_a_relayed_command_is_measured_through_every_phase_and_its_overhead_is_all_but_it(
    api: Stack, tmp_path: Path
) -> None:
    wire = Crossed(api.transport)
    relayed = await relay_to(api, tmp_path, wire=wire)
    clock = Read()
    runner = TransportRelayImpl(
        lambda: api.container.managers.exec_relay,
        lambda: RequestContext(request_id=new_id(), app=RUNNER),
        first_poll=timedelta(milliseconds=5),
        last_poll=timedelta(milliseconds=20),
        clock=clock,
    )
    before = observed("run")
    spec = command(relayed.epoch, "sleep", "0.3")
    waiting = asyncio.ensure_future(runner.run(relayed.workspace, spec, seal=NO_SEAL))
    (item_id,) = await claims(relayed.host, waiting)
    assert (await waiting).exit_code == 0
    # Its claim carried its detail, so the host read it with no call of its
    # own; it still timed its parts by its own clock and sent them with its
    # result: the command took what it slept.
    assert "detail" not in wire.calls and len(wire.asked) == 1
    (answered,) = wire.answered
    times = answered["times"]
    assert sorted(times) == ["command", "detail", "start"]
    assert times["detail"] >= 0 and times["start"] >= 0 and 0.3 <= times["command"] < 3
    progress = await api.container.managers.exec_relay.watch(
        _request(), api.owner.org_id, item_id, -1
    )
    assert progress.times is not None and progress.times.host is not None
    gained = {
        name: (count - before[name][0], total - before[name][1])
        for name, (count, total) in observed("run").items()
    }
    # One observation of each phase, the host's own as it timed them; and
    # together they are the item's whole time, from its making to the read.
    assert {name: count for name, (count, _) in gained.items()} == dict.fromkeys(gained, 1.0)
    for phase in ("detail", "start", "command"):
        assert gained[phase][1] == pytest.approx(times[phase])
    sent_at, read_at = clock.reads[0], clock.reads[-1]
    whole = (read_at - progress.times.created_at).total_seconds()
    assert sum(gained[phase][1] for phase in PHASES) == pytest.approx(whole)
    # The overhead is the time from the runner's send to its read, less the
    # command's own.
    overhead = (read_at - sent_at).total_seconds() - times["command"]
    assert gained["overhead"][1] == pytest.approx(overhead)
    assert gained["overhead"][1] < whole


async def test_a_host_sends_no_times_to_a_platform_that_keeps_none(
    api: Stack, tmp_path: Path
) -> None:
    wire = Crossed(api.transport, earlier=True)
    relayed = await relay_to(api, tmp_path, wire=wire)
    spec = command(relayed.epoch, "echo", "done")
    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, seal=NO_SEAL))
    await claims(relayed.host, waiting)
    assert (await waiting).stdout == "done\n"
    (answered,) = wire.answered
    assert "times" not in answered
    # Its claim carried no detail, so the host read it by its route, and it
    # sent its output to the store, since that platform takes none inline.
    assert wire.calls.count("detail") == 1 and "POST upload" in wire.calls
    assert "data" not in answered["output"]


async def test_a_short_commands_output_rides_its_result_after_one_call_to_claim_and_read_it(
    api: Stack, tmp_path: Path
) -> None:
    wire = Crossed(api.transport)
    relayed = await relay_to(api, tmp_path, wire=wire, flush_seconds=60.0)
    printed: list[tuple[str, str]] = []

    async def sink(stream: str, text: str) -> None:
        printed.append((stream, text))

    spec = command(relayed.epoch, "sh", "-c", "echo one; echo two >&2")
    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, sink, seal=NO_SEAL))
    await claims(relayed.host, waiting)
    ran = await waiting
    assert (ran.exit_code, ran.stdout, ran.stderr) == (0, "one\n", "two\n")
    # Its claim carried its detail, and it ended within its first window: no
    # part went apart from its result, which carried its output whole, and
    # nothing crossed the store.
    moved = ("detail", "POST parts", "POST upload", "POST result")
    assert [call for call in wire.calls if call in moved] == ["POST result"], wire.calls
    (answered,) = wire.answered
    assert sorted(answered["output"]) == ["data", "digest", "size"]
    assert printed == []


async def test_a_read_within_the_bound_rides_its_result_and_one_past_it_crosses_the_store(
    api: Stack, tmp_path: Path
) -> None:
    wire = Crossed(api.transport)
    relayed = await relay_to(api, tmp_path, wire=wire)
    within = bytes(range(256)) * 256
    (tmp_path / "workspace" / "data.bin").write_bytes(within + b"!")
    for asked, crosses in ((len(within), False), (len(within) + 1, True)):
        wire.calls.clear()
        reading = asyncio.ensure_future(
            relayed.runner.read_file(relayed.workspace, "data.bin", asked)
        )
        pace = Pace()
        while not reading.done():
            await pace.after(await relayed.host.tick() is not None)
        assert await reading == (within + b"!")[:asked]
        assert ("POST upload" in wire.calls) is crosses, wire.calls


async def test_an_empty_read_to_a_platform_that_takes_nothing_inline_lands_from_the_store(
    api: Stack, tmp_path: Path
) -> None:
    wire = Crossed(api.transport, earlier=True)
    relayed = await relay_to(api, tmp_path, wire=wire)
    (tmp_path / "workspace" / "empty.log").write_bytes(b"")
    reading = asyncio.ensure_future(relayed.runner.read_file(relayed.workspace, "empty.log", 64))
    # The read lands with its file: one refused would leave it to its lease.
    async with asyncio.timeout(20):
        pace = Pace()
        while not reading.done():
            await pace.after(await relayed.host.tick() is not None)
        assert await reading == b""
    # Its one result named the file it sent to the store, with no bytes
    # inline, not even an empty file's.
    (answered,) = wire.answered
    assert "data" not in answered["file"] and answered["file"]["size"] == 0
    assert "POST upload" in wire.calls


class Handed(Crossed):
    """The stack, as `Crossed` notes it, keeping each write's file as the
    claim's detail hands it."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        super().__init__(inner)
        self.files: list[dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)
        if request.url.path == "/v1/hosts/me/claims" and response.status_code == 200:
            item = json.loads(await response.aread())["item"] or {}
            detail = item.get("detail") or {}
            if detail.get("file_in") is not None:
                self.files.append(detail["file_in"])
        return response


async def test_a_small_write_rides_in_its_claim_and_reaches_the_workspace_checked(
    api: Stack, tmp_path: Path
) -> None:
    wire = Handed(api.transport)
    relayed = await relay_to(api, tmp_path, wire=wire)
    data = "naïve notes\n".encode() * 100
    writing = asyncio.ensure_future(
        relayed.runner.write_file(relayed.workspace, "notes.md", data, relayed.epoch)
    )
    pace = Pace()
    while not writing.done():
        await pace.after(await relayed.host.tick() is not None)
    await writing
    assert (tmp_path / "workspace" / "notes.md").read_bytes() == data
    # The file came in the claim, by its size, its digest, and its bytes.
    (handed,) = wire.files
    assert sorted(handed) == ["data", "digest", "size"] and handed["size"] == len(data)


async def test_a_result_a_replica_refuses_is_pushed_again_as_an_earlier_release_takes_it(
    api: Stack, tmp_path: Path
) -> None:
    wire = Crossed(api.transport, rolling=True)
    relayed = await relay_to(api, tmp_path, wire=wire)
    spec = command(relayed.epoch, "false")
    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, seal=NO_SEAL))
    # The item settles with the command's own outcome: a result never taken
    # would leave it to its lease, and the runner waiting.
    async with asyncio.timeout(20):
        await claims(relayed.host, waiting)
        assert (await waiting).exit_code == 1
    refused, taken = wire.answered
    assert "times" in refused and "data" in refused["output"]
    # Again without its times, and what rode inline went to the store, by
    # the same size and digest.
    assert "times" not in taken and "data" not in taken["output"]
    assert taken["output"] == {k: v for k, v in refused["output"].items() if k != "data"}
    rest = {key: value for key, value in refused.items() if key not in ("times", "output")}
    assert {key: value for key, value in taken.items() if key != "output"} == rest


class Slowed(httpx.AsyncBaseTransport):
    """The store, answering each GET `seconds` late."""

    def __init__(self, inner: httpx.AsyncBaseTransport, seconds: float) -> None:
        self._inner = inner
        self._seconds = seconds

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            await asyncio.sleep(self._seconds)
        return await self._inner.handle_async_request(request)


async def test_a_relayed_writes_download_is_in_its_overhead_and_not_in_its_command(
    api: Stack, tmp_path: Path
) -> None:
    fetch = 0.3
    assert api.store is not None
    wire = Crossed(api.transport)
    relayed = await relay_to(replace(api, store=Slowed(api.store, fetch)), tmp_path, wire=wire)
    clock = Read()
    runner = TransportRelayImpl(
        lambda: api.container.managers.exec_relay,
        lambda: RequestContext(request_id=new_id(), app=RUNNER),
        first_poll=timedelta(milliseconds=5),
        last_poll=timedelta(milliseconds=20),
        clock=clock,
    )
    before = observed("write_file")
    # Past what rides in the item, so it crosses the store.
    written = b"w" * (INLINE_BYTES + 1)
    waiting = asyncio.ensure_future(
        runner.write_file(relayed.workspace, "in.txt", written, relayed.epoch)
    )
    await claims(relayed.host, waiting)
    await waiting
    assert (tmp_path / "workspace" / "in.txt").read_bytes() == written
    # The download lands in the start, before the command, by the host's
    # own clock.
    (answered,) = wire.answered
    times = answered["times"]
    assert times["command"] < fetch <= times["start"]
    gained = {name: total - before[name][1] for name, (_, total) in observed("write_file").items()}
    assert gained["command"] == pytest.approx(times["command"])
    # The overhead is the send to the read less the command alone, so it
    # holds the download. The runner's first read of its clock sets the
    # write's deadline, a moment before its send.
    sent_at, read_at = clock.reads[0], clock.reads[-1]
    overhead = (read_at - sent_at).total_seconds() - times["command"]
    assert gained["overhead"] == pytest.approx(overhead, abs=1e-3)
    assert gained["overhead"] >= fetch


class Sized(httpx.AsyncBaseTransport):
    """The stack, noting the path and the size of every request the host
    sends it."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.sent: list[tuple[str, int]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.sent.append((request.url.path, len(await request.aread())))
        return await self._inner.handle_async_request(request)


# Check 6: a command whose stdout and stderr each hold max_output settles
# with a result request of a few KiB, and its output reads back whole.


async def test_a_command_that_fills_both_streams_settles_with_a_result_of_a_few_kib(
    api: Stack, tmp_path: Path
) -> None:
    wire = Sized(api.transport)
    relayed = await relay_to(api, tmp_path, wire=wire)
    most = CommandSpec.model_fields["max_output"].default
    script = f"import sys; sys.stdout.write('o' * {most}); sys.stderr.write('é' * {most})"
    spec = command(relayed.epoch, "python3", "-c", script)
    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, seal=NO_SEAL))
    await claims(relayed.host, waiting)
    ran = await waiting
    assert (ran.exit_code, ran.truncated) == (0, False)
    assert (ran.stdout, ran.stderr) == ("o" * most, "é" * most), "read back whole"
    (result,) = [size for path, size in wire.sent if path.endswith("/result")]
    print(f"a result request of {result} bytes; both streams of {most} read back whole")
    assert result < 2048, f"a result request of {result} bytes"
    uploads = [size for path, size in wire.sent if path.endswith("/upload")]
    assert uploads and max(uploads) < 1024, "the output went straight to the store"


@pytest.mark.parametrize("kind", [StopKind.CANCEL, StopKind.INTERRUPT])
async def test_a_stop_over_the_control_stream_ends_a_running_command_at_once(
    relayed: Relayed, kind: StopKind
) -> None:
    relay = relayed.api.container.managers.exec_relay
    listening = asyncio.ensure_future(relayed.host.listen())
    asleep = 30
    spec = command(relayed.epoch, "sh", "-c", f"echo started; sleep {asleep}")
    started = asyncio.Event()

    async def sink(stream: str, text: str) -> None:
        if "started" in text:
            started.set()

    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, sink, seal=NO_SEAL))
    running = asyncio.ensure_future(claims(relayed.host, waiting))
    await asyncio.wait_for(started.wait(), 10)
    (item,) = await relayed.api.container.storage.get_exec_relay_storage().read_items_by_key(
        relayed.api.owner.org_id, relayed.workspace.id, spec.key, 10
    )
    item_id = item.id
    stopped_at = time.monotonic()
    await relay.stop(_request(), relayed.api.owner.org_id, item_id, kind, relayed.epoch)
    with pytest.raises(ToolFailed) as ended:
        await waiting
    took = time.monotonic() - stopped_at
    assert ended.value.failure is ToolFailure.INTERRUPTED
    assert kind.value in ended.value.message
    print(f"{kind.value}: the command ended {took:.3f}s after its stop")
    # Held against the command's own run, never a fixed bound: a stop that
    # missed its tree lets it sleep out its 30 s, and one that reached it
    # ends it at the control stream's next read, a second or so later.
    assert took < asleep / 2, f"the command ended {took:.1f}s after its stop"
    progress = await relay.watch(_request(), relayed.api.owner.org_id, item_id, -1)
    assert progress.state is ExecState.DONE
    assert progress.outcome is not None and progress.outcome.stopped is kind
    await running
    listening.cancel()


async def test_an_item_past_the_hosts_ceilings_is_refused_at_once(relayed: Relayed) -> None:
    spec = command(relayed.epoch, "true")
    other = relayed.workspace.model_copy(
        update={
            "spec": IsolationSpec(
                mode=IsolationMode.HOST,
                egress=EgressPolicy(mode=EgressMode.ALLOWLIST, hosts=("example.com",)),
            )
        }
    )
    waiting = asyncio.ensure_future(relayed.runner.run(other, spec, seal=NO_SEAL))
    await claims(relayed.host, waiting)
    with pytest.raises(Exception, match="egress: egress beyond this host's allowlist") as refused:
        await waiting
    assert getattr(refused.value, "code", None) == "refused_by_host"


async def test_a_command_past_the_owners_paths_or_isolation_is_refused_by_name_before_it_runs(
    api: Stack, tmp_path: Path
) -> None:
    marker = tmp_path / "ran"

    async def refused(relayed: Relayed) -> str:
        spec = command(relayed.epoch, "sh", "-c", f"touch {marker}")
        waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, seal=NO_SEAL))
        await claims(relayed.host, waiting)
        with pytest.raises(Exception) as refusal:
            await waiting
        assert getattr(refusal.value, "code", None) == "refused_by_host"
        return str(refusal.value)

    # A workspace whose directory its owner does not let a result read: its
    # call is refused at the claim, by the ceiling's name, and runs nothing.
    (tmp_path / "paths").mkdir()
    elsewhere = await relay_to(api, tmp_path / "paths", readable=("/srv/work",))
    assert "readable: a read outside this host's readable paths" in await refused(elsewhere)
    # A directory, on a host whose owner asks a container at the least.
    (tmp_path / "isolation").mkdir()
    weaker = await relay_to(api, tmp_path / "isolation", min_isolation=HostMode.container)
    assert "min_isolation: isolation directory below this host's minimum" in await refused(weaker)
    assert not marker.exists()


async def test_an_item_whose_spec_opens_egress_its_fields_close_is_refused_and_nothing_run(
    api: Stack, tmp_path: Path
) -> None:
    # The host's owner lets nothing leave, and the item's fields say nothing
    # does; its spec, as the wire hands its detail over, opens egress.
    wire = Widened(api.transport)
    relayed = await relay_to(api, tmp_path, wire=wire)
    marker = tmp_path / "workspace" / "ran"
    spec = command(relayed.epoch, "touch", str(marker))
    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, seal=NO_SEAL))
    assert len(await claims(relayed.host, waiting)) == 1
    with pytest.raises(Exception, match="its spec and its fields differ on egress") as refused:
        await waiting
    assert getattr(refused.value, "code", None) == "refused_by_host"
    assert wire.widened >= 1
    assert not marker.exists()


def real(location: str) -> str:
    """The directory as a command run in it prints it."""
    return str(Path(location).resolve())


async def test_a_bound_workspace_whose_directory_went_is_made_again_and_its_call_runs(
    api: Stack, tmp_path: Path
) -> None:
    opened = IsolationSpec(mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.OPEN))
    host, _ = await directory_host(api, (await api.pool("pool-a")).id, tmp_path)
    agent_session_id, location = await bound_on(host, api, opened)
    shutil.rmtree(location)  # its host's disk lost it
    ran = await run_on(host, api, agent_session_id, opened, "pwd")
    assert (ran.exit_code, ran.stdout) == (0, f"{real(location)}\n")


@pytest.mark.integration
@pytest.mark.skipif(not docker_runs(), reason="needs a local Docker")
async def test_a_bound_sessions_stopped_container_is_prepared_again_and_its_call_runs(
    api: Stack, tmp_path: Path
) -> None:
    sealed = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))
    host = await container_host(api, (await api.pool("pool-a")).id, tmp_path)
    agent_session_id, name = await bound_on(host, api, sealed)
    try:
        await run_on(host, api, agent_session_id, sealed, "touch", "kept")
        # Stopped, as a reboot or a Docker restart leaves it.
        stop = ["docker", "stop", "-t", "0", name]
        await asyncio.to_thread(subprocess.run, stop, check=True, capture_output=True)
        ran = await run_on(host, api, agent_session_id, sealed, "ls")
        assert (ran.exit_code, ran.stdout) == (0, "kept\n")  # a new instance, over its files
    finally:
        provider = AgentWorkspaceContainerImpl(DEFAULT_IMAGE, timedelta(seconds=30), "purge")
        await provider.purge(api.owner.org_id, agent_session_id)


@pytest.mark.integration
@pytest.mark.skipif(not docker_runs(), reason="needs a local Docker")
async def test_a_relayed_command_runs_on_its_host_as_the_user_it_names(
    api: Stack, tmp_path: Path
) -> None:
    sealed = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))
    host = await container_host(api, (await api.pool("pool-a")).id, tmp_path)
    agent_session_id, _ = await bound_on(host, api, sealed)
    try:
        ids = ("sh", "-c", "id -u; id -g")
        apart = await run_on(host, api, agent_session_id, sealed, *ids, user=APART)
        own = await run_on(host, api, agent_session_id, sealed, *ids)
        assert (apart.exit_code, apart.stdout) == (0, "65534\n65534\n"), apart.stderr
        assert (own.exit_code, own.stdout) == (0, "0\n0\n"), own.stderr
    finally:
        provider = AgentWorkspaceContainerImpl(DEFAULT_IMAGE, timedelta(seconds=30), "purge")
        await provider.purge(api.owner.org_id, agent_session_id)


async def test_a_command_that_names_a_user_never_reaches_a_host_that_reads_no_user(
    api: Stack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host that reads `exec` work from before a command named its user
    would run one as its workspace's own: it is handed none."""
    monkeypatch.setattr(host_agent, "EXEC_VERSION", USER_VERSION - 1)
    relayed = await relay_to(api, tmp_path)
    marker = tmp_path / "workspace" / "ran"
    spec = command(relayed.epoch, "touch", str(marker), user=APART)
    with pytest.raises(CapabilityMissing, match="reads exec work from before a command named"):
        await relayed.runner.run(relayed.workspace, spec, seal=NO_SEAL)
    assert await relayed.host.claim_once() is None
    assert not marker.exists()


async def test_a_directory_host_refuses_a_command_that_names_a_user_and_runs_nothing(
    relayed: Relayed, tmp_path: Path
) -> None:
    """Every command of a directory runs as the host's one user: one that
    names another is refused there, never run as that one."""
    marker = tmp_path / "workspace" / "ran"
    spec = command(relayed.epoch, "touch", str(marker), user=APART)
    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, seal=NO_SEAL))
    assert len(await claims(relayed.host, waiting)) == 1
    with pytest.raises(Exception, match="as one user, never as 65534:65534"):
        await waiting
    assert not marker.exists()


@pytest.mark.parametrize("served", [True, False])
async def test_a_relayed_call_names_its_sessions_agent_project_to_the_hosts_ceilings(
    api: Stack, tmp_path: Path, served: bool
) -> None:
    agent_project = await api.container.managers.agent_projects.create_agent_project(
        api.owner, make_agent_project()
    )
    serves = agent_project.id if served else new_id()
    relayed = await relay_to(api, tmp_path, agent_project.id, serves)
    waiting = asyncio.ensure_future(
        relayed.runner.run(relayed.workspace, command(relayed.epoch, "echo", "ours"), seal=NO_SEAL)
    )
    handed = await claims(relayed.host, waiting)
    assert len(handed) == 1
    if served:
        ran = await waiting
        assert (ran.exit_code, ran.stdout) == (0, "ours\n")
    else:
        with pytest.raises(
            Exception, match="agent_projects: an agent project this host does not serve"
        ):
            await waiting


async def test_a_host_whose_owner_takes_no_persons_command_refuses_a_command_by_hand(
    relayed: Relayed,
) -> None:
    api = relayed.api
    agent_session_id = relayed.workspace.id
    await api.container.managers.agent_workspaces.pinned(api.owner, agent_session_id, DIRECTORY)
    watch = build_watch(api.container.managers, api.container.stream)
    person = _in_person(api.owner)
    await watch.take_control(person, agent_session_id)
    command = HandCommand(key=new_id(), argv=("echo", "by hand"))
    await watch.run_command(person, agent_session_id, command)
    handled = None
    for _ in range(100):
        handled = await relayed.host.claim_once()
        if handled is not None:
            break
        await asyncio.sleep(0.01)
    assert handled is not None
    assert handled.refused == [
        "people_commands: a person's command, which this host does not accept"
    ]
    ended = await watch.command(person, agent_session_id, command.key, -1)
    assert ended.state is ExecState.DONE and ended.outcome is not None
    assert ended.outcome.refused == "refused_by_host" and ended.outcome.exit_code is None


def _in_person(of: TenantContext) -> TenantContext:
    """The owner at the portal, signed in on a session of their own."""
    return build_context(
        _request(),
        user_id=of.user_id,
        org_id=of.org_id,
        role=of.role,
        permissions=permissions_of(of.role),
        credential_kind=CredentialKind.AUTH_SESSION_TOKEN,
    )


class FailsOnceAt(httpx.AsyncBaseTransport):
    """The stack, except that the first call whose path ends in `suffix`
    fails as `failure` says: an answer with that status, or the connection
    dropped."""

    def __init__(self, inner: httpx.AsyncBaseTransport, suffix: str, failure: int | None) -> None:
        self._inner = inner
        self._suffix = suffix
        self._failure = failure
        self.failed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not self.failed and request.url.path.endswith(self._suffix):
            self.failed = True
            if self._failure is None:
                raise httpx.ConnectError("the connection was reset", request=request)
            error = {"error": {"code": "unavailable", "message": "try again"}}
            return httpx.Response(self._failure, json=error)
        return await self._inner.handle_async_request(request)


@pytest.mark.parametrize(("suffix", "failure"), [("/lease", 503), ("/result", None)])
async def test_a_renewal_or_a_result_the_platform_fails_to_take_is_sent_again(
    api: Stack, tmp_path: Path, suffix: str, failure: int | None
) -> None:
    wire = FailsOnceAt(api.transport, suffix, failure)
    relayed = await relay_to(api, tmp_path, wire=wire)
    spec = command(relayed.epoch, "sh", "-c", "sleep 0.5; echo done", seconds=5)
    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, seal=NO_SEAL))
    handed = await asyncio.wait_for(claims(relayed.host, waiting), 10)
    ran = await waiting
    assert wire.failed
    assert (ran.exit_code, ran.stdout, len(handed)) == (0, "done\n", 1)


async def test_a_last_part_the_wire_drops_keeps_the_commands_result(
    api: Stack, tmp_path: Path
) -> None:
    # Nothing is sent while the command runs, so its one part is its last;
    # a platform of an earlier release takes no output in the result, so
    # the part goes.
    wire = FailsOnceAt(Crossed(api.transport, earlier=True), "/parts", None)
    relayed = await relay_to(api, tmp_path, wire=wire, flush_seconds=60.0)
    spec = command(relayed.epoch, "sh", "-c", "echo done", seconds=5)
    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, seal=NO_SEAL))
    handed = await asyncio.wait_for(claims(relayed.host, waiting), 10)
    ran = await waiting
    assert wire.failed
    assert (ran.exit_code, ran.stdout, len(handed)) == (0, "done\n", 1)


class Pushed(httpx.AsyncBaseTransport):
    """The stack, noting the parts of each push of output a host sends, each
    by its place, its stream, and its bytes."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.pushes: list[list[tuple[int, str, bytes]]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/parts"):
            parts = json.loads(await request.aread())["parts"]
            self.pushes.append(
                [(p["seq"], p["stream"], base64.b64decode(p["data"])) for p in parts]
            )
        return await self._inner.handle_async_request(request)


async def test_a_window_of_output_is_one_push_that_holds_every_part_in_it(
    api: Stack, tmp_path: Path
) -> None:
    # The whole command runs within one window, and a platform of an
    # earlier release takes no output in the result, so the window goes.
    wire = Pushed(Crossed(api.transport, earlier=True))
    relayed = await relay_to(api, tmp_path, wire=wire, flush_seconds=60.0)
    printed: list[tuple[str, str]] = []

    async def sink(stream: str, text: str) -> None:
        printed.append((stream, text))

    spec = command(
        relayed.epoch,
        "sh",
        "-c",
        "echo one; sleep 0.1; echo two >&2; sleep 0.1; echo three",
        seconds=5,
    )
    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, sink, seal=NO_SEAL))
    await asyncio.wait_for(claims(relayed.host, waiting), 10)
    ran = await waiting
    window = [(0, "stdout", b"one\n"), (1, "stderr", b"two\n"), (2, "stdout", b"three\n")]
    assert wire.pushes == [window]
    assert printed == [(stream, data.decode()) for _, stream, data in window]
    assert (ran.stdout, ran.stderr) == ("one\nthree\n", "two\n")


async def test_a_window_past_what_one_push_carries_goes_in_whole_characters_in_more(
    api: Stack, tmp_path: Path
) -> None:
    wire = Pushed(api.transport)
    relayed = await relay_to(api, tmp_path, wire=wire, flush_seconds=60.0, window_chars=10**9)
    printed: list[str] = []

    async def sink(stream: str, text: str) -> None:
        printed.append(text)

    # Three bytes a character, so no push of PUSH_BYTES ends on one's edge.
    euros = "\u20ac" * 60_000
    script = f"import sys; sys.stdout.write('\\u20ac' * {len(euros)})"
    spec = command(relayed.epoch, "python3", "-c", script, seconds=10)
    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, sink, seal=NO_SEAL))
    await asyncio.wait_for(claims(relayed.host, waiting), 20)
    ran = await waiting
    sizes = [sum(len(data) for _, _, data in push) for push in wire.pushes]
    assert sizes == [PUSH_BYTES - PUSH_BYTES % 3, len(euros.encode()) - PUSH_BYTES + PUSH_BYTES % 3]
    seqs = [seq for push in wire.pushes for seq, _, _ in push]
    assert seqs == list(range(len(seqs)))
    assert "".join(printed) == ran.stdout == euros


async def test_a_short_command_beside_a_long_one_runs_within_its_deadline(
    relayed: Relayed,
) -> None:
    long = asyncio.ensure_future(
        relayed.runner.run(
            relayed.workspace, command(relayed.epoch, "sh", "-c", "sleep 2"), seal=NO_SEAL
        )
    )
    looping = asyncio.ensure_future(claims(relayed.host, long))
    await asyncio.sleep(0.2)  # the long one is claimed and runs
    short = command(relayed.epoch, "echo", "short", seconds=1)
    ran = await relayed.runner.run(relayed.workspace, short, seal=NO_SEAL)
    assert (ran.exit_code, ran.stdout, ran.timed_out) == (0, "short\n", False)
    assert not long.done()
    assert (await long).exit_code == 0
    assert len(await looping) == 2


class Bearers(httpx.AsyncBaseTransport):
    """The stack, noting the credential each control stream opens with."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.opened: list[str] = []
        self.again = asyncio.Event()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/hosts/me/control"):
            self.opened.append(request.headers.get("authorization", ""))
            self.again.set()
        return await self._inner.handle_async_request(request)


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


async def test_a_host_that_rotates_while_its_stream_is_open_keeps_its_stream_on_the_new_credential(
    api: Stack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(exec_relay_service, "STREAM_SPAN", timedelta(milliseconds=200))
    bearers = Bearers(api.transport)
    clock = Clock()
    relayed = await relay_to(api, tmp_path, wire=bearers, now=clock)
    host = relayed.host
    listening = asyncio.ensure_future(host_main.listen(host))
    await asyncio.wait_for(bearers.again.wait(), 5)
    first = f"Bearer {host.credential.token}"
    clock.now += (host.credential.expires_at - host.credential.issued_at) / 2
    assert await host.rotate_if_due()
    rotated = len(bearers.opened)
    renewed = f"Bearer {host.credential.token}"
    while renewed not in bearers.opened[rotated:]:
        bearers.again.clear()
        await asyncio.wait_for(bearers.again.wait(), 5)
    # The stream ended and was opened again on the new credential; the one
    # rotated away was never shown again, so the host was never revoked.
    assert first not in bearers.opened[rotated:]
    statuses = await api.container.managers.hosts.get_hosts(api.owner, host_pool(host))
    assert [status.host.revoked_at for status in statuses] == [None]
    await host.beat()
    # A stop still reaches the host over the stream it opened again, once
    # the command runs there: a stop that lands before it starts finds
    # nothing to end.
    spec = command(relayed.epoch, "sh", "-c", "echo started; sleep 30")
    started = asyncio.Event()

    async def sink(stream: str, text: str) -> None:
        if "started" in text:
            started.set()

    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, sink, seal=NO_SEAL))
    running = asyncio.ensure_future(claims(host, waiting))
    await asyncio.wait_for(started.wait(), 10)
    (item,) = await _items(relayed, spec)
    await api.container.managers.exec_relay.stop(
        _request(), api.owner.org_id, item, StopKind.CANCEL, relayed.epoch
    )
    with pytest.raises(ToolFailed):
        await asyncio.wait_for(waiting, 10)
    await running
    listening.cancel()


def host_pool(host: HostAgent) -> UUID:
    return UUID(host.credential.pool_id)


async def _items(relayed: Relayed, spec: CommandSpec) -> list[UUID]:
    """The exec relay's items under the call's key, once its host runs one."""
    relay = relayed.api.container.managers.exec_relay
    storage = relayed.api.container.storage.get_exec_relay_storage()
    for _ in range(500):
        items = await storage.read_items_by_key(
            relayed.api.owner.org_id, relayed.workspace.id, spec.key, 10
        )
        if items:
            progress = await relay.watch(_request(), relayed.api.owner.org_id, items[0].id, -1)
            if progress.state is ExecState.RUNNING:
                return [item.id for item in items]
        await asyncio.sleep(0.01)
    raise AssertionError("no host ran the command")


def _request() -> RequestContext:
    return RequestContext(request_id=new_id(), app=RUNNER)
