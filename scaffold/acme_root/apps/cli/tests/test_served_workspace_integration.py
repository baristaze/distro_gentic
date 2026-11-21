"""A session's workspace from the CLI, over Postgres: the person signed in
through the API in process, the session runner's container as it boots, and
the CLI's own code, which starts the session and, for a local workspace,
serves it through the host program's claim loop, here on a directory of this
machine.

A local session is pinned to a pool of one of its own. Its person's client
trades a one-use key for a host's credential of that pool, prepares the
workspace, and runs the session's tool calls; their results reach the
model. With the client gone, the next workspace call waits on the resource
and never reaches the cloud; once a client serves again, the call runs. A
session in an agent project, served under a ceilings file written as the
host's README shows, syncs its repository and runs its command. A session
started on the cloud has its workspace prepared by the cloud pool.

Needs a migrated database (`make migrate`)."""

import asyncio
import shutil
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from api_support import sign_in_as
from host_support import Stack, postgres, probes, stack
from runner_support import TOOLS, answers, assistant, runs

from acme.apps.cli import main as cli
from acme.apps.host import ceilings as owner_file
from acme.apps.host import main as host_main
from acme.apps.host import serving
from acme.apps.host.agent import HostAgent
from acme.apps.host.ceilings import Ceilings
from acme.apps.host.config import Settings
from acme.apps.host.exec_relay import ExecutorRelayImpl
from acme.client.claimant.enrollment import ClientFactory
from acme.client.client import ApiClient
from acme.client.types.agent_sessions import WorkspacePlace
from acme.client.types.hosts import IsolationMode as HostMode
from acme.infra.agent_workspaces import (
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
)
from acme.infra.agent_workspaces.host import AgentWorkspaceHostImpl
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import DEFAULT_PATH, TransportLocalImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import ProviderName
from acme.om import platform_root
from acme.om.agent_projects.storage import AgentProjectStorageInterface
from acme.om.agent_steps.rules import message_step
from acme.om.agent_steps.types.agent_step import AgentStepType
from acme.om.agent_steps.types.header import LoopOutcome, ParkReason
from acme.om.agent_workspaces.impl.agent_projects import WorkspaceAgentProjectsBoundImpl
from acme.om.agent_workspaces.impl.reader import RepositoryReaderGitImpl
from acme.om.agent_workspaces.types.source import RepositoryBinding
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.placement.kinds import PlacementWorkKind
from acme.om.platform_root import PlatformPorts, ProductKinds
from acme.services.api.seed import seed_platform
from acme.workers.agent_session_runner.container import RunnerContainer
from acme.workers.agent_session_runner.settings import AgentSessionRunnerSettings

from contracts.agent_project_storage import make_agent_project

pytestmark = pytest.mark.integration

KIND = assistant().model_copy(update={"private_data": False})
"""Works in a directory of its own, which a person's machine gives. It holds
no private data, so a call after a command's output runs unattended."""
ON_VMS = assistant(
    IsolationSpec(mode=IsolationMode.VM, egress=EgressPolicy(mode=EgressMode.OPEN))
).model_copy(update={"name": "vm_assistant"})
"""Works on a VM of its own, which the cloud pool gives."""

SETTINGS = AgentSessionRunnerSettings.model_validate(
    {"_env_file": None, "environment": "test", "runner_id": "runner-served"}
)
API_URL = "http://test"
WAIT = 10.0
"""The most a case waits for the client to do what it was asked."""
GIT = shutil.which("git")
HOST_README = Path(__file__).parents[2] / "host" / "README.md"
"""The host's README, whose ceilings file a person copies."""


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[Stack]:
    storage = postgres()
    # A local stack's API: a session starts in no agent project, so its
    # workspace binds no repository.
    async with stack(
        tmp_path / "api", storage, agent_kinds=(KIND, ON_VMS), tools=TOOLS, environment="local"
    ) as running:
        yield running
    await storage.close()


async def a_runner(api: Stack, remote: Path | None = None) -> RunnerContainer:
    """The session runner's container as it boots, its agent projects each
    binding `remote`, the repository on this disk, when one is named."""
    storage = postgres()
    on_disk = None
    if remote is not None:
        on_disk = OnDisk(storage.get_agent_project_storage(), remote)
    container = RunnerContainer.over(
        SETTINGS,
        storage,
        api.container.infra,
        IntegrationsOverImpl(IdentityProviderAbsentImpl(), scripted_model_providers()),
        ports=PlatformPorts(
            workspace_agent_projects=on_disk,
            kinds=ProductKinds(agents=(KIND, ON_VMS), tools=lambda _: TOOLS),
        ),
    )
    await seed_platform(container.storage, container.managers, api.owner, (KIND, ON_VMS))
    return container


class OnDisk(WorkspaceAgentProjectsBoundImpl):
    """The agent projects' answers, each binding the repository on this disk
    in place of its forge's."""

    def __init__(self, storage: AgentProjectStorageInterface, remote: Path) -> None:
        super().__init__(storage)
        self._url = f"file://{remote}"

    async def binding_of(
        self, ctx: TenantContext, agent_project_id: UUID
    ) -> RepositoryBinding | None:
        bound = await super().binding_of(ctx, agent_project_id)
        return None if bound is None else bound.model_copy(update={"repository": self._url})


@pytest.fixture
async def runner(api: Stack) -> AsyncIterator[RunnerContainer]:
    container = await a_runner(api)
    yield container
    await container.storage.close()


@pytest.fixture
async def person(api: Stack) -> AsyncIterator[ApiClient]:
    """The owner, signed in at the CLI."""
    async with httpx.AsyncClient(transport=api.transport, base_url=API_URL) as http:
        headers = await sign_in_as(http, api.container, api.email, api.owner.org_id)
    async with ApiClient(
        API_URL,
        app="cli",
        app_version="cli@test",
        token=headers["Authorization"].removeprefix("Bearer "),
        transport=api.transport,
        store_transport=api.store,
    ) as client:
        yield client


@pytest.fixture
def machine(
    api: Stack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[], list[HostAgent]]:
    """This machine, its owner's ceilings written in the case."""
    root = tmp_path / "workspaces"
    return this_machine(
        api,
        tmp_path,
        monkeypatch,
        lambda _settings: Ceilings(
            agent_projects=None,
            min_isolation=HostMode.directory,
            egress=None,
            readable=(str(root),),
        ),
    )


def this_machine(
    api: Stack,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owners: Callable[[Settings], Ceilings],
    search_path: str = DEFAULT_PATH,
) -> Callable[[], list[HostAgent]]:
    """This machine, as the CLI's host program finds it: its owner's home
    and the ceilings `owners` reads there, and the hosts its clients
    started, each making a directory per workspace under its root and
    running commands there, on `search_path`."""
    root = tmp_path / "workspaces"
    started: list[HostAgent] = []

    def build(settings: Settings, client_for: ClientFactory | None) -> HostAgent:
        agents: list[HostAgent] = []
        transport = TransportLocalImpl(
            settings.records_path,
            SecretsLocalImpl(None),
            BrokerNullImpl(),
            search_path=search_path,
        )
        executor = ExecutorRelayImpl(
            lambda: agents[0].client(),
            {IsolationMode.HOST: transport},
            {IsolationMode.HOST: AgentWorkspaceHostImpl(root)},
            flush_seconds=0.0,
            renew_seconds=0.2,
        )
        agent = HostAgent(
            settings,
            owners(settings),
            probes(HostMode.directory),
            api.client,
            executor,
        )
        agents.append(agent)
        started.append(agent)
        return agent

    owner = replace(api.settings(tmp_path / "host-home", None), beat_seconds=0.05)
    monkeypatch.setattr(host_main, "host_agent", build)
    monkeypatch.setattr(serving, "settings_from_env", lambda: owner)
    return lambda: started


async def until[T](
    read: Callable[[], Awaitable[T]],
    check: Callable[[T], bool],
    beside: asyncio.Future[Any] | None = None,
) -> T:
    """What `read` answers once `check` holds of it, within `WAIT`; what
    ended `beside`, the client's serving, if it ends first."""
    async with asyncio.timeout(WAIT):
        while True:
            if beside is not None and beside.done():
                beside.result()
                raise AssertionError("the client stopped serving")
            value = await read()
            if check(value):
                return value
            await asyncio.sleep(0.05)


def resolved(location: str) -> str:
    """The workspace's directory as the command run in it prints it."""
    return str(Path(location).resolve())


def model_of(runner: RunnerContainer) -> ModelProviderScriptedImpl:
    model = runner.integrations.get_model_providers().get(ProviderName.ANTHROPIC)
    assert isinstance(model, ModelProviderScriptedImpl)
    return model


async def said(runner: RunnerContainer, api: Stack, agent_session_id: UUID, text: str) -> None:
    step = message_step(new_id(), utcnow(), agent_session_id, api.owner, text)
    await runner.managers.agent_sessions.receive(api.owner, agent_session_id, [step])


async def started_local(
    api: Stack, person: ApiClient, agent_project: UUID | None = None
) -> tuple[UUID, asyncio.Future[Any]]:
    """`agent-session start --workspace local`, as the CLI runs it, in
    `agent_project` when one is named: the session, pinned to its own pool,
    and the serving that runs until cancelled."""
    serving_task = asyncio.ensure_future(
        cli.start_session(
            person,
            API_URL,
            KIND.name,
            "where it runs",
            agent_project=agent_project,
            workspace=WorkspacePlace.local,
            as_json=False,
        )
    )
    page = await until(
        lambda: person.agent_sessions(),
        lambda page: any(s.title == "where it runs" for s in page.items),
        serving_task,
    )
    (session,) = [s for s in page.items if s.title == "where it runs"]
    hosts = api.container.managers.hosts
    await until(
        lambda: hosts.placement_of(api.owner, session.id),
        lambda state: state.pool is not None,
        serving_task,
    )
    return session.id, serving_task


async def stopped(serving_task: asyncio.Future[Any]) -> None:
    serving_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await serving_task


async def bound_on_the_client(runner: RunnerContainer, api: Stack, agent_session_id: UUID) -> UUID:
    """The first loop waits on the resource with no model call, the client
    claims the prepare, and the workspace is bound to its host: its id."""
    managers = runner.managers
    parked = await managers.loop.run(api.owner, agent_session_id)
    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert parked.park.reason is ParkReason.LEASABLE_RESOURCE
    binding = await until(
        lambda: managers.exec_relay.binding_of(api.owner, agent_session_id),
        lambda bound: bound is not None,
    )
    assert binding is not None
    await managers.agent_sessions.wake_agent_session(api.owner, agent_session_id, parked.park)
    return binding.host_id


async def a_call_ran(
    runner: RunnerContainer,
    api: Stack,
    agent_session_id: UUID,
    host_id: UUID,
    *argv: str,
    prints: str | None = None,
) -> None:
    """The next loop's tool call runs on the client's host, and what it
    printed, `prints` or the workspace's directory, reaches the model."""
    model = model_of(runner)
    before = len(model.calls)
    model.add(runs(*(argv or ("pwd",))))
    model.add(answers("On my person's own machine."))
    ended = await runner.managers.loop.run(api.owner, agent_session_id)
    assert ended.outcome is LoopOutcome.SUCCEEDED, ended
    binding = await runner.managers.exec_relay.binding_of(api.owner, agent_session_id)
    assert binding is not None and binding.host_id == host_id
    assert len(model.calls) == before + 2
    assert (prints or resolved(binding.location)) in repr(model.calls[-1])


async def test_a_local_session_runs_its_tool_call_through_its_persons_client(
    api: Stack,
    runner: RunnerContainer,
    person: ApiClient,
    machine: Callable[[], list[HostAgent]],
) -> None:
    agent_session_id, serving_task = await started_local(api, person)
    hosts = api.container.managers.hosts
    placed = await until(
        lambda: hosts.placement_of(api.owner, agent_session_id),
        lambda state: state.pool is not None and not state.waiting,
    )
    assert placed.pool is not None and placed.pool.agent_session_id == agent_session_id
    await said(runner, api, agent_session_id, "Where do you run?")

    host_id = await bound_on_the_client(runner, api, agent_session_id)
    (client,) = machine()
    assert host_id == UUID(client.credential.claimant_id)
    assert UUID(client.credential.pool_id) == placed.pool.id
    await a_call_ran(runner, api, agent_session_id, host_id)
    page = await runner.managers.agent_steps.get_agent_steps(api.owner, agent_session_id, 0, 100)
    assert [s.type for s in page.items].count(AgentStepType.TOOL_RESPONSE) == 1
    await stopped(serving_task)


async def test_with_its_client_gone_a_local_session_waits_and_never_reaches_the_cloud(
    api: Stack,
    runner: RunnerContainer,
    person: ApiClient,
    machine: Callable[[], list[HostAgent]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The cloud pool would hold any workspace it is asked for.
    asked: list[UUID] = []

    async def runs_any(spec: IsolationSpec) -> bool:
        return True

    async def prepare(ctx: object, agent_session_id: UUID, *rest: object) -> None:
        asked.append(agent_session_id)
        raise IsolationRefused("no VM here", clears=True)

    monkeypatch.setattr(runner.managers.cloud_pool, "runs", runs_any)
    monkeypatch.setattr(runner.managers.cloud_pool, "prepare", prepare)
    agent_session_id, serving_task = await started_local(api, person)
    await said(runner, api, agent_session_id, "Where do you run?")
    first = await bound_on_the_client(runner, api, agent_session_id)
    await a_call_ran(runner, api, agent_session_id, first)

    # The client stops: it ends its host, and the session waits for another.
    await stopped(serving_task)
    hosts = api.container.managers.hosts
    state = await hosts.placement_of(api.owner, agent_session_id)
    assert state.pool is not None and state.pool.agent_session_id == agent_session_id
    assert state.waiting
    model = model_of(runner)
    calls = len(model.calls)
    await said(runner, api, agent_session_id, "And now?")
    parked = await runner.managers.loop.run(api.owner, agent_session_id)
    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert parked.park.reason is ParkReason.LEASABLE_RESOURCE
    assert len(model.calls) == calls, "no model call while it waits"
    assert asked == [], "the cloud pool is never asked"
    assert await runner.managers.work.has_open(
        api.owner, PlacementWorkKind.WORKSPACE, agent_session_id
    )

    # A client serves it again: the call runs there, on its new host.
    again = asyncio.ensure_future(cli.attach_to(person, API_URL, agent_session_id, as_json=False))
    second = await until(
        lambda: _bound_host(runner, api, agent_session_id),
        lambda host: host is not None and host != first,
        again,
    )
    assert second is not None
    await runner.managers.agent_sessions.wake_agent_session(
        api.owner, agent_session_id, parked.park
    )
    await a_call_ran(runner, api, agent_session_id, second, "pwd", "-L")
    assert len(machine()) == 2 and asked == []
    await stopped(again)


async def _bound_host(runner: RunnerContainer, api: Stack, agent_session_id: UUID) -> UUID | None:
    binding = await runner.managers.exec_relay.binding_of(api.owner, agent_session_id)
    return None if binding is None else binding.host_id


async def test_a_session_started_on_the_cloud_has_its_workspace_prepared_by_the_cloud_pool(
    api: Stack,
    runner: RunnerContainer,
    person: ApiClient,
    machine: Callable[[], list[HostAgent]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[UUID, IsolationMode]] = []
    cloud_pool = runner.managers.cloud_pool

    async def runs_vms(spec: IsolationSpec) -> bool:
        return spec.mode is IsolationMode.VM

    async def prepare(
        ctx: object, agent_session_id: UUID, spec: IsolationSpec, *rest: object
    ) -> None:
        asked.append((agent_session_id, spec.mode))
        raise IsolationRefused("its VM is starting", clears=True)

    monkeypatch.setattr(cloud_pool, "runs", runs_vms)
    monkeypatch.setattr(cloud_pool, "prepare", prepare)
    started = await cli.start_session(
        person,
        API_URL,
        ON_VMS.name,
        "on the cloud",
        agent_project=None,
        workspace=WorkspacePlace.cloud,
        as_json=False,
    )
    await said(runner, api, started.id, "Build it.")
    parked = await runner.managers.loop.run(api.owner, started.id)

    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert parked.park.reason is ParkReason.LEASABLE_RESOURCE
    assert asked == [(started.id, IsolationMode.VM)]
    placed = await api.container.managers.hosts.placement_of(api.owner, started.id)
    assert placed.pool is None, "of the cloud"
    assert machine() == [], "nothing serves it from this machine"


def a_remote(where: Path) -> Path:
    """An agent project's repository on this disk, served bare, its default
    branch holding a README."""
    remote, seed = where / "remote.git", where / "seed"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / "README.md").write_text("a checkout of the agent project\n")
    for args in (
        ("add", "README.md"),
        ("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "1"),
        ("push", "-q", str(remote), "main"),
    ):
        subprocess.run(["git", "-C", str(seed), *args], check=True, capture_output=True)
    return remote


def as_the_readme_shows(home: Path, **this_machine: str) -> Path:
    """The ceilings file of the host's README, written into `home`, each
    line `this_machine` names set to what this machine gives."""
    block = HOST_README.read_text().split("```toml\n", 1)[1].split("```", 1)[0]
    lines = []
    for line in block.splitlines():
        key = line.split("=", 1)[0].strip()
        lines.append(f"{key} = {this_machine.pop(key)}" if key in this_machine else line)
    assert not this_machine, f"the README's file names no {sorted(this_machine)}"
    home.mkdir(parents=True, exist_ok=True)
    path = home / "ceilings.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.mark.skipif(GIT is None, reason="git is not on this host")
async def test_a_local_session_in_an_agent_project_syncs_and_runs_under_the_readmes_ceilings(
    api: Stack,
    person: ApiClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert GIT is not None
    # The runner reads the agent project's repository from this disk, as a
    # deployed one does not.
    monkeypatch.setattr(
        platform_root,
        "RepositoryReaderGitImpl",
        lambda **options: RepositoryReaderGitImpl(**{**options, "on_disk": True}),
    )
    runner = await a_runner(api, a_remote(tmp_path))
    agent_project = make_agent_project()
    await api.container.storage.get_agent_project_storage().create_agent_project(
        api.owner.org_id, agent_project, ()
    )
    root = tmp_path / "workspaces"
    # The README's file, with this machine's agent project, its directory,
    # its open egress, and its workspaces' root.
    written = as_the_readme_shows(
        tmp_path / "host-home",
        agent_projects=f'["{agent_project.id}"]',
        min_isolation='"directory"',
        egress='"open"',
        readable=f'["{root}"]',
    )
    read: list[Path] = []

    def owners(settings: Settings) -> Ceilings:
        read.append(settings.ceilings_path)
        return owner_file.load(settings.ceilings_path)

    machine = this_machine(
        api, tmp_path, monkeypatch, owners, search_path=f"{Path(GIT).parent}:{DEFAULT_PATH}"
    )
    agent_session_id, serving_task = await started_local(api, person, agent_project.id)
    await said(runner, api, agent_session_id, "What does this project hold?")
    host_id = await bound_on_the_client(runner, api, agent_session_id)
    assert len(machine()) == 1 and read == [written], "the client holds the README's file"

    # The loop syncs the checkout through the client before its call, and
    # the call reads what the repository holds.
    await a_call_ran(
        runner,
        api,
        agent_session_id,
        host_id,
        "cat",
        "README.md",
        prints="a checkout of the agent project",
    )
    await stopped(serving_task)
    await runner.storage.close()
