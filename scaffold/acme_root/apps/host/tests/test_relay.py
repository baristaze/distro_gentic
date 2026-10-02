"""A host runs relayed work against the live app, in process. A tool call
the runner relays runs once, on the host that holds the workspace, through
its local transport: its output streams back a part at a time and its
result lands under the call's key. A cancel or an interrupt the platform
records reaches the host over the control stream it holds open, and ends
the command at once. A host's routes take its own credential alone."""

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from contracts.project_storage import make_binding, make_project
from host_support import Stack, probes

from acme.apps.host.agent import HostAgent
from acme.apps.host.ceilings import Ceilings
from acme.apps.host.relay import ExecutorRelayImpl
from acme.client.types import IsolationMode as HostMode
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports import CommandResult, CommandSpec, RecordSeal
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import TransportLocalImpl
from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec, Workspace
from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext
from acme.om.exceptions import ToolFailed
from acme.om.placement.types.work import ExecPayload
from acme.om.relay.impl.transport import TransportRelayImpl
from acme.om.relay.types.exec import ExecState, StopKind
from acme.om.steps.types.header import ToolFailure

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
    api: Stack, tmp_path: Path, project_id: UUID | None = None, serves: UUID | None = None
) -> Relayed:
    """A host of the tenant's pool that holds a session's workspace, a
    directory it runs commands in through the engine's local transport, and
    the runner's relay to it. With `serves`, the host's ceilings serve that
    project alone, and the session belongs to `project_id`."""
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
        api.client,
        executor,
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
    runner = TransportRelayImpl(
        lambda: managers.relay,
        lambda: RequestContext(request_id=new_id(), app=RUNNER),
        first_poll=timedelta(milliseconds=5),
        last_poll=timedelta(milliseconds=20),
    )
    workspace = Workspace(id=session.id, org_id=api.owner.org_id, spec=DIRECTORY, location="")
    return Relayed(api, host, executor, runner, workspace, epoch, host_id)


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


def _request() -> RequestContext:
    return RequestContext(request_id=new_id(), app=RUNNER)
