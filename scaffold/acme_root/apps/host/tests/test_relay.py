"""A host runs relayed work against the live app, in process. A tool call
the runner relays runs once, on the host that holds the workspace, through
its local transport: its output streams back a part at a time and its
result lands under the call's key. A cancel or an interrupt the platform
records reaches the host over the control stream it holds open, and ends
the command at once. A host's routes take its own credential alone. A
workspace whose instance went since its host prepared it, as after a
reboot or a Docker restart, is prepared again, and its call runs."""

import asyncio
import shutil
import subprocess
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from contracts.agent_session_storage import make_session
from contracts.project_storage import make_binding, make_project
from host_support import Stack, Widened, container_host, directory_host, docker_runs, probes

from acme.apps.host import main as host_main
from acme.apps.host.agent import HostAgent
from acme.apps.host.ceilings import Ceilings
from acme.apps.host.relay import ExecutorRelayImpl
from acme.client.client import ApiClient
from acme.client.types import IsolationMode as HostMode
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports import CommandResult, CommandSpec, RecordSeal
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import TransportLocalImpl
from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec, Workspace
from acme.infra.workspaces.container import DEFAULT_IMAGE, WorkspaceContainerImpl
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
from acme.om.placement.types.work import ExecPayload
from acme.om.relay.impl.transport import TransportRelayImpl
from acme.om.relay.types.exec import ExecState, StopKind
from acme.om.steps.types.header import ToolFailure
from acme.om.tenancy.rules import permissions_of
from acme.om.watch.root import build_watch
from acme.om.watch.types.control import HandCommand
from acme.services.api.services.impl import relay as relay_service

RUNNER = AppContext(type=AppType.WORKER, version="runner@test")
DIRECTORY = IsolationSpec(mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.NONE))


async def _nothing(data: bytes) -> bytes | None:
    return None


NO_SEAL = RecordSeal(seal=_nothing, open=_nothing)


@dataclass
class Relayed:
    api: Stack
    host: HostAgent
    executor: ExecutorRelayImpl
    runner: TransportRelayImpl
    workspace: Workspace
    epoch: int
    host_id: UUID


@pytest.fixture
async def relayed(api: Stack, tmp_path: Path) -> AsyncIterator[Relayed]:
    yield await relay_to(api, tmp_path)


async def relay_to(
    api: Stack,
    tmp_path: Path,
    project_id: UUID | None = None,
    serves: UUID | None = None,
    wire: httpx.AsyncBaseTransport | None = None,
    now: Callable[[], datetime] | None = None,
) -> Relayed:
    """A host of the tenant's pool that holds a session's workspace, a
    directory it runs commands in through the engine's local transport, and
    the runner's relay to it. With `serves`, the host's ceilings serve that
    project alone, and the session belongs to `project_id`. With `wire`, the
    host reaches the platform through it, and with `now` it reads its time."""
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
        flush_seconds=0.0,
        renew_seconds=0.2,
    )
    host = HostAgent(
        api.settings(tmp_path / "home", await api.token(pool.id)),
        Ceilings(
            projects=None if serves is None else frozenset({serves}),
            min_isolation=HostMode.directory,
            egress=frozenset(),
            readable=(str(where),),
        ),
        probes(HostMode.directory),
        lambda token: ApiClient(
            "http://test",
            app="api",
            app_version="host@test",
            token=token,
            transport=wire or api.transport,
        ),
        executor,
        now=now or (lambda: datetime.now(UTC)),
    )
    agents.append(host)
    await host.start()
    managers = api.container.managers
    session = await managers.agent_sessions.create_session(api.owner, make_session())
    if project_id is not None:
        await api.container.storage.get_project_storage().bind_session(
            api.owner.org_id, make_binding(session.id, project_id)
        )
    await managers.hosts.place_session(api.owner, session.id, pool.id)
    host_id = UUID(host.credential.host_id)
    await managers.relay.bind_workspace(api.owner, session.id, host_id, str(where))
    epoch = await managers.steps.begin_run(api.owner, session.id)
    workspace = Workspace(id=session.id, org_id=api.owner.org_id, spec=DIRECTORY, location="")
    return Relayed(api, host, executor, runner_of(api), workspace, epoch, host_id)


def runner_of(api: Stack) -> TransportRelayImpl:
    """The runner's relay to the tenant's hosts."""
    return TransportRelayImpl(
        lambda: api.container.managers.relay,
        lambda: RequestContext(request_id=new_id(), app=RUNNER),
        first_poll=timedelta(milliseconds=5),
        last_poll=timedelta(milliseconds=20),
    )


async def bound_on(host: HostAgent, api: Stack, spec: IsolationSpec) -> tuple[UUID, str]:
    """A session of the host's pool whose workspace the host prepared and
    holds: its id, and where the host made it."""
    managers = api.container.managers
    session = await managers.agent_sessions.create_session(api.owner, make_session())
    await managers.hosts.place_session(api.owner, session.id, host_pool(host))
    await managers.relay.ask_prepare(api.owner, session.id, spec)
    assert await host.claim_once() is not None
    await host.idle()
    held = await managers.relay.binding_of(api.owner, session.id)
    assert held is not None
    return session.id, held.location


async def run_on(
    host: HostAgent, api: Stack, session_id: UUID, spec: IsolationSpec, *argv: str
) -> CommandResult:
    """A command of the session's next run, relayed to the host that holds
    its workspace, while that host claims."""
    epoch = await api.container.managers.steps.begin_run(api.owner, session_id)
    workspace = Workspace(id=session_id, org_id=api.owner.org_id, spec=spec, location="")
    waiting = asyncio.ensure_future(
        runner_of(api).run(workspace, command(epoch, *argv), seal=NO_SEAL)
    )
    await claims(host, waiting)
    return await waiting


def command(epoch: int, *argv: str, seconds: float = 30) -> CommandSpec:
    return CommandSpec(
        argv=argv,
        key=new_id(),
        epoch=epoch,
        deadline=datetime.now(UTC) + timedelta(seconds=seconds),
        effect="unsafe",
    )


async def claims(host: HostAgent, until: asyncio.Future[CommandResult]) -> list[UUID]:
    """The host's loop while the runner waits: the exec items it was
    handed, by the relay's id."""
    handed: list[UUID] = []
    while not until.done():
        one = await host.tick()
        if one is not None:
            handed.append(ExecPayload.model_validate(one.item.payload).item_id)
        else:
            await asyncio.sleep(0.01)
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
    epoch = await relayed.api.container.managers.steps.begin_run(
        relayed.api.owner, relayed.workspace.id
    )
    again = await relayed.runner.outcome(relayed.workspace, spec.key, epoch, seal=NO_SEAL)
    assert again is not None and again.stdout == "one\nthree\n"
    assert await relayed.host.claim_once() is None


@pytest.mark.parametrize("kind", [StopKind.CANCEL, StopKind.INTERRUPT])
async def test_a_stop_over_the_control_stream_ends_a_running_command_at_once(
    relayed: Relayed, kind: StopKind
) -> None:
    relay = relayed.api.container.managers.relay
    listening = asyncio.ensure_future(relayed.host.listen())
    spec = command(relayed.epoch, "sh", "-c", "echo started; sleep 30")
    started = asyncio.Event()

    async def sink(stream: str, text: str) -> None:
        if "started" in text:
            started.set()

    waiting = asyncio.ensure_future(relayed.runner.run(relayed.workspace, spec, sink, seal=NO_SEAL))
    running = asyncio.ensure_future(claims(relayed.host, waiting))
    await asyncio.wait_for(started.wait(), 10)
    (item,) = await relayed.api.container.storage.get_relay_storage().read_items_by_key(
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
    assert took < 2, f"the command ended {took:.1f}s after its stop"
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
    with pytest.raises(Exception, match="egress beyond this host's allowlist") as refused:
        await waiting
    assert getattr(refused.value, "code", None) == "refused_by_host"


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
    session_id, location = await bound_on(host, api, opened)
    shutil.rmtree(location)  # its host's disk lost it
    ran = await run_on(host, api, session_id, opened, "pwd")
    assert (ran.exit_code, ran.stdout) == (0, f"{real(location)}\n")


@pytest.mark.integration
@pytest.mark.skipif(not docker_runs(), reason="needs a local Docker")
async def test_a_bound_sessions_stopped_container_is_prepared_again_and_its_call_runs(
    api: Stack, tmp_path: Path
) -> None:
    sealed = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))
    host = await container_host(api, (await api.pool("pool-a")).id, tmp_path)
    session_id, name = await bound_on(host, api, sealed)
    try:
        await run_on(host, api, session_id, sealed, "touch", "kept")
        # Stopped, as a reboot or a Docker restart leaves it.
        stop = ["docker", "stop", "-t", "0", name]
        await asyncio.to_thread(subprocess.run, stop, check=True, capture_output=True)
        ran = await run_on(host, api, session_id, sealed, "ls")
        assert (ran.exit_code, ran.stdout) == (0, "kept\n")  # a new instance, over its files
    finally:
        provider = WorkspaceContainerImpl(DEFAULT_IMAGE, timedelta(seconds=30))
        await provider.purge(api.owner.org_id, session_id)


@pytest.mark.parametrize("served", [True, False])
async def test_a_relayed_call_names_its_sessions_project_to_the_hosts_ceilings(
    api: Stack, tmp_path: Path, served: bool
) -> None:
    project = await api.container.managers.projects.create_project(api.owner, make_project())
    serves = project.id if served else new_id()
    relayed = await relay_to(api, tmp_path, project.id, serves)
    waiting = asyncio.ensure_future(
        relayed.runner.run(relayed.workspace, command(relayed.epoch, "echo", "ours"), seal=NO_SEAL)
    )
    handed = await claims(relayed.host, waiting)
    assert len(handed) == 1
    if served:
        ran = await waiting
        assert (ran.exit_code, ran.stdout) == (0, "ours\n")
    else:
        with pytest.raises(Exception, match="a project this host does not serve"):
            await waiting


async def test_a_host_whose_owner_takes_no_persons_command_refuses_a_command_by_hand(
    relayed: Relayed,
) -> None:
    api = relayed.api
    session_id = relayed.workspace.id
    await api.container.managers.workspaces.pinned(api.owner, session_id, DIRECTORY)
    watch = build_watch(api.container.managers, api.container.stream)
    person = _in_person(api.owner)
    await watch.take_control(person, session_id)
    command = HandCommand(key=new_id(), argv=("echo", "by hand"))
    await watch.run_command(person, session_id, command)
    handled = None
    for _ in range(100):
        handled = await relayed.host.claim_once()
        if handled is not None:
            break
        await asyncio.sleep(0.01)
    assert handled is not None
    assert handled.refused == ["a person's command, which this host does not accept"]
    ended = await watch.command(person, session_id, command.key, -1)
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
        credential_kind=CredentialKind.SESSION_TOKEN,
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
    monkeypatch.setattr(relay_service, "STREAM_SPAN", timedelta(milliseconds=200))
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
    await api.container.managers.relay.stop(
        _request(), api.owner.org_id, item, StopKind.CANCEL, relayed.epoch
    )
    with pytest.raises(ToolFailed):
        await asyncio.wait_for(waiting, 10)
    await running
    listening.cancel()


def host_pool(host: HostAgent) -> UUID:
    return UUID(host.credential.pool_id)


async def _items(relayed: Relayed, spec: CommandSpec) -> list[UUID]:
    """The relay's items under the call's key, once its host runs one."""
    relay = relayed.api.container.managers.relay
    storage = relayed.api.container.storage.get_relay_storage()
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
