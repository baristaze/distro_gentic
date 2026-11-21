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
session started on the cloud has its workspace prepared by the cloud pool.

Needs a migrated database (`make migrate`)."""

import asyncio
from collections.abc import AsyncIterator, Callable
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
from acme.infra.transports.local import TransportLocalImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import ProviderName
from acme.om.agent_steps.rules import message_step
from acme.om.agent_steps.types.agent_step import AgentStepType
from acme.om.agent_steps.types.header import LoopOutcome, ParkReason
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id, utcnow
from acme.om.placement.kinds import PlacementWorkKind
from acme.om.platform_root import PlatformPorts, ProductKinds
from acme.services.api.seed import seed_platform
from acme.workers.agent_session_runner.container import RunnerContainer
from acme.workers.agent_session_runner.settings import AgentSessionRunnerSettings

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


@pytest.fixture
async def runner(api: Stack) -> AsyncIterator[RunnerContainer]:
    container = RunnerContainer.over(
        SETTINGS,
        postgres(),
        api.container.infra,
        IntegrationsOverImpl(IdentityProviderAbsentImpl(), scripted_model_providers()),
        ports=PlatformPorts(kinds=ProductKinds(agents=(KIND, ON_VMS), tools=lambda _: TOOLS)),
    )
    await seed_platform(container.storage, container.managers, api.owner, (KIND, ON_VMS))
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
    """This machine, as the CLI's host program finds it: its owner's home
    and ceilings, and the hosts its clients started, each making a directory
    per workspace under its root and running commands there."""
    root = tmp_path / "workspaces"
    started: list[HostAgent] = []

    def build(settings: Settings, client_for: ClientFactory | None) -> HostAgent:
        agents: list[HostAgent] = []
        transport = TransportLocalImpl(
            settings.records_path, SecretsLocalImpl(None), BrokerNullImpl()
        )
        executor = ExecutorRelayImpl(
            lambda: agents[0].client(),
            {IsolationMode.HOST: transport},
            {IsolationMode.HOST: AgentWorkspaceHostImpl(root)},
            flush_seconds=0.0,
            renew_seconds=0.2,
            commands=frozenset({"pwd"}),
        )
        agent = HostAgent(
            settings,
            Ceilings(
                agent_projects=None,
                min_isolation=HostMode.directory,
                egress=None,
                readable=(str(root),),
                commands=frozenset({"pwd"}),
            ),
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
    read: Callable[[], Any], check: Callable[[T], bool], beside: asyncio.Future[Any] | None = None
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


async def started_local(api: Stack, person: ApiClient) -> tuple[UUID, asyncio.Future[Any]]:
    """`agent-session start --workspace local`, as the CLI runs it: the
    session, pinned to its own pool, and the serving that runs until
    cancelled."""
    serving_task = asyncio.ensure_future(
        cli.start_session(
            person,
            API_URL,
            KIND.name,
            "where it runs",
            agent_project=None,
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
    await managers.agent_sessions.wake_agent_session(api.owner, agent_session_id, parked.park)
    return binding.host_id


async def a_call_ran(
    runner: RunnerContainer, api: Stack, agent_session_id: UUID, host_id: UUID, *argv: str
) -> None:
    """The next loop's tool call runs on the client's host, and what it
    printed reaches the model."""
    model = model_of(runner)
    before = len(model.calls)
    model.add(runs(*(argv or ("pwd",))))
    model.add(answers("On my person's own machine."))
    ended = await runner.managers.loop.run(api.owner, agent_session_id)
    assert ended.outcome is LoopOutcome.SUCCEEDED, ended
    binding = await runner.managers.exec_relay.binding_of(api.owner, agent_session_id)
    assert binding is not None and binding.host_id == host_id
    assert len(model.calls) == before + 2
    assert resolved(binding.location) in repr(model.calls[-1])


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
    second = await until(lambda: _bound_host(runner, api, agent_session_id), lambda h: h != first)
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
