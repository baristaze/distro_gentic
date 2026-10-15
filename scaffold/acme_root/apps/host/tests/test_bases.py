"""A workspace on a base inside a customer's wall, against the live app, in
process. The host that prepares it builds the base once, in a workspace of
its own, and keeps it in its own store: the next workspace on it starts from
the store's copy with no setup run, and nothing of it reaches the
platform's bucket. A setup command that fails keeps nothing, and the host
answers the prepare unbuilt, so the run that waits says which command
failed and how, one too long for the answer cut to fit it. A command in a
workspace on a base, and what a checkout's attach sends it, runs on the
base the host keeps. The setup is given no secret and no credential of the
host's, and a base that holds the value of a secret the host keeps is not
kept. A prepare that may build its base asks for its setup's egress, and an
owner who closed egress refuses it before anything runs."""

import asyncio
import hashlib
import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import get_args
from uuid import UUID

import pytest
from host_support import Pace, Stack, probes
from test_exec_relay import claims, command, runner_of

from acme.apps.host.agent import HostAgent
from acme.apps.host.bases import base_key
from acme.apps.host.ceilings import Ceilings
from acme.apps.host.exec_relay import ExecutorRelayImpl
from acme.apps.host.snapshots import HostSnapshots
from acme.client.types import IsolationMode as HostMode
from acme.infra.agent_workspaces import (
    AgentWorkspace,
    AgentWorkspaceBase,
    Durability,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
)
from acme.infra.agent_workspaces.twin import AgentWorkspaceTwinImpl
from acme.infra.buckets import Buckets
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports import CommandResult, CommandSpec, OutputSink, RecordSeal
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.twin import TransportTwinImpl, TwinReply
from acme.om.agent_projects.types.agent_project import SetupCommand
from acme.om.agent_workspaces.impl.git import INCOMING
from acme.om.exec_relay.impl.workspaces import PlacedWorkspacesRelayedImpl
from acme.om.placement.kinds import PlacementWorkKind
from acme.om.tools.impl.bases import PREFIX
from acme.om.work.types.work_item import WorkStatus

from contracts.agent_session_storage import make_agent_session

SETUP = ("pip install acme-tools", "echo built >> /opt/count")
BASE = AgentWorkspaceBase(
    image="python:3.14-slim", setup=SETUP, egress=EgressPolicy(mode=EgressMode.OPEN)
)
ON_BASE = IsolationSpec(
    mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE), base=BASE
)
SECRET = "tok-0123456789abcdef"
LONGEST = get_args(SetupCommand)[1].max_length
"""The longest setup command an agent project's workspace base allows."""


async def _unsealed(data: bytes) -> None:
    return None


NO_SEAL = RecordSeal(seal=_unsealed, open=_unsealed)


class Setup:
    """The twin transport's handler: each command it runs, the environment
    it gets, the exit code a case asks of a command, and what a command
    writes into the base."""

    def __init__(self) -> None:
        self.ran: list[str] = []
        self.envs: list[Mapping[str, str]] = []
        self.exits: dict[str, int] = {}

    async def __call__(self, command: CommandSpec, env: Mapping[str, str]) -> TwinReply:
        self.ran.append(command.argv[-1])
        self.envs.append(dict(env))
        return TwinReply(exit_code=self.exits.get(command.argv[-1], 0))


class ContainerTransportTwin(TransportTwinImpl):
    """The twin transport, standing in for a host's container transport: it
    runs a command in a container workspace the twin made."""

    async def run(
        self,
        workspace: AgentWorkspace,
        command: CommandSpec,
        on_output: OutputSink | None = None,
        *,
        seal: RecordSeal,
    ) -> CommandResult:
        return await super().run(_inside(workspace), command, on_output, seal=seal)

    async def write_file(
        self, workspace: AgentWorkspace, path: str, data: bytes, epoch: int
    ) -> None:
        await super().write_file(_inside(workspace), path, data, epoch)


def _inside(workspace: AgentWorkspace) -> AgentWorkspace:
    twin = workspace.spec.model_copy(update={"mode": IsolationMode.TWIN})
    return workspace.model_copy(update={"spec": twin})


class BuiltContainerTwin(AgentWorkspaceTwinImpl):
    """The twin, standing in for a host's container provider: a snapshot of
    a workspace holds what a test wrote there and each command the
    transport ran there, so a base holds its setup. The hash of the base
    each workspace started from is kept, by workspace."""

    def __init__(self, transport: TransportTwinImpl) -> None:
        super().__init__()
        self._transport = transport
        self.started_from: dict[UUID, str] = {}
        self.writes: bytes = b""

    async def prepare(
        self,
        org_id: UUID,
        agent_workspace_id: UUID,
        spec: IsolationSpec,
        snapshot: bytes | None = None,
        base: bytes | None = None,
        *,
        building: bool = False,
    ) -> AgentWorkspace:
        if base is not None:
            self.started_from[agent_workspace_id] = hashlib.sha256(base).hexdigest()
        twin = spec.model_copy(update={"mode": IsolationMode.TWIN, "durability": Durability.CACHE})
        made = await super().prepare(
            org_id, agent_workspace_id, twin, snapshot, base, building=building
        )
        return made.model_copy(update={"spec": spec})

    async def snapshot(self, workspace: AgentWorkspace) -> bytes:
        ran = [
            command.argv[-1]
            for command in self._transport.commands
            if (workspace.id, command.key) in self._transport.records
        ]
        return await super().snapshot(workspace) + self.writes + "\n".join(ran).encode()


class Host:
    def __init__(self, agent: HostAgent, twin: BuiltContainerTwin, setup: Setup, store: Path):
        self.agent = agent
        self.twin = twin
        self.setup = setup
        self.store = store

    async def claimed(self) -> None:
        assert await self.agent.claim_once() is not None
        await self.agent.idle()


async def a_host(
    api: Stack, pool_id: UUID, where: Path, *, egress: frozenset[str] | None = None
) -> Host:
    """A host of the pool that runs a container per workspace, keeps their
    snapshots and bases in its own store, and whose owner allows `egress`,
    open by default; its secret store holds one value for the tenant."""
    setup = Setup()
    transport = ContainerTransportTwin(SecretsLocalImpl(None), BrokerNullImpl(), setup)
    twin = BuiltContainerTwin(transport)
    store = where / "snapshots"
    secrets = where / "secrets"
    await SecretsLocalImpl(secrets).put(api.owner.org_id, "SERVICE_TOKEN", SECRET)
    snapshots = HostSnapshots(store, secrets)
    agents: list[HostAgent] = []
    executor = ExecutorRelayImpl(
        lambda: agents[0].client(),
        {IsolationMode.CONTAINER: transport},
        {IsolationMode.CONTAINER: twin},
        snapshots=snapshots,
        snapshot_modes=lambda: frozenset({IsolationMode.CONTAINER}),
        flush_seconds=0.0,
        renew_seconds=0.2,
    )
    checks = replace(probes(HostMode.container), snapshots={HostMode.container: snapshots.usable})
    pool_token = await api.token(pool_id)
    agent = HostAgent(
        replace(api.settings(where / "home", None), enrollment_token=pool_token),
        Ceilings(agent_projects=None, min_isolation=HostMode.container, egress=egress),
        checks,
        api.client,
        executor,
    )
    agents.append(agent)
    await agent.start()
    return Host(agent, twin, setup, store)


async def a_pinned_session(api: Stack, pool_id: UUID) -> UUID:
    managers = api.container.managers
    session = await managers.agent_sessions.create_agent_session(api.owner, make_agent_session())
    await managers.hosts.place_session(api.owner, session.id, pool_id)
    return session.id


def kept_base(host: Host, api: Stack) -> Path:
    return host.store / str(api.owner.org_id) / "bases" / base_key(ON_BASE)


async def test_a_host_builds_a_base_once_in_its_store_and_the_next_workspace_runs_no_setup(
    api: Stack, tmp_path: Path
) -> None:
    exec_relay = api.container.managers.exec_relay
    pool = await api.pool()
    first = await a_pinned_session(api, pool.id)
    second = await a_pinned_session(api, pool.id)
    host = await a_host(api, pool.id, tmp_path)

    assert await exec_relay.ask_prepare(api.owner, first, ON_BASE)
    await host.claimed()
    assert host.setup.ran == list(SETUP), "the host built the base"
    assert await exec_relay.ask_prepare(api.owner, second, ON_BASE)
    await host.claimed()

    assert host.setup.ran == list(SETUP), "the second workspace ran no setup"
    for agent_session_id in (first, second):
        assert await exec_relay.binding_of(api.owner, agent_session_id) is not None
    kept = kept_base(host, api).read_bytes()
    started = host.twin.started_from
    assert started[first] == started[second] == hashlib.sha256(kept).hexdigest()
    buckets = api.container.infra.get_buckets()
    in_bucket = await buckets.list(api.owner.org_id, Buckets.SNAPSHOTS, PREFIX, 10)
    assert in_bucket == [], "nothing of it reached the platform's bucket"


async def test_a_failed_setup_keeps_nothing_and_the_run_waits_with_its_command_and_exit_code(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    host = await a_host(api, pool.id, tmp_path)
    host.setup.exits["pip install acme-tools"] = 1
    placed = PlacedWorkspacesRelayedImpl(lambda: managers.exec_relay, lambda: managers.hosts)

    with pytest.raises(IsolationRefused) as asked:
        await placed.held_on_host(api.owner, agent_session_id, ON_BASE)
    await host.claimed()

    assert asked.value.clears, "it waits on the resource"
    assert host.setup.ran == ["pip install acme-tools"], "the setup stopped at the failure"
    assert not kept_base(host, api).exists(), "no half-built base"
    assert host.twin.started_from == {}, "no workspace started from one"
    assert await managers.exec_relay.binding_of(api.owner, agent_session_id) is None
    row = await managers.work.latest_for_target(
        api.owner, PlacementWorkKind.WORKSPACE, agent_session_id
    )
    assert row is not None and row.status is WorkStatus.QUEUED, "a host builds again later"
    failed = "the base's setup command 1, 'pip install acme-tools', exited 1"
    assert row.last_error is not None and failed in row.last_error
    with pytest.raises(IsolationRefused, match=failed) as waits:
        await placed.held_on_host(api.owner, agent_session_id, ON_BASE)
    assert waits.value.clears


async def test_a_setup_command_at_the_longest_an_agent_project_allows_fails_and_the_wait_names_it(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    host = await a_host(api, pool.id, tmp_path)
    longest = "pip install " + "x" * (LONGEST - len("pip install "))
    spec = ON_BASE.model_copy(update={"base": BASE.model_copy(update={"setup": (longest,)})})
    host.setup.exits[longest] = 2
    placed = PlacedWorkspacesRelayedImpl(lambda: managers.exec_relay, lambda: managers.hosts)

    with pytest.raises(IsolationRefused):
        await placed.held_on_host(api.owner, agent_session_id, spec)
    await host.claimed()

    row = await managers.work.latest_for_target(
        api.owner, PlacementWorkKind.WORKSPACE, agent_session_id
    )
    assert row is not None and row.last_error is not None, "the platform took the answer"
    cut = r"the base's setup command 1, 'pip install x+…\[\d+ more characters\]', exited 2"
    assert re.search(cut, row.last_error)
    with pytest.raises(IsolationRefused, match=cut) as waits:
        await placed.held_on_host(api.owner, agent_session_id, spec)
    assert waits.value.clears


async def test_a_command_in_a_workspace_on_a_base_runs_on_the_base_the_host_keeps(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    host = await a_host(api, pool.id, tmp_path)
    assert await managers.exec_relay.ask_prepare(api.owner, agent_session_id, ON_BASE)
    await host.claimed()
    assert await managers.exec_relay.binding_of(api.owner, agent_session_id) is not None
    host.twin.started_from.clear()

    epoch = await managers.agent_steps.begin_run(api.owner, agent_session_id)
    workspace = AgentWorkspace(
        id=agent_session_id, org_id=api.owner.org_id, spec=ON_BASE, location=""
    )
    runner = runner_of(api)
    # A checkout's attach brings its bundle in, then runs git over it.
    written = asyncio.ensure_future(runner.write_file(workspace, INCOMING, b"bundle", epoch))
    pace = Pace()
    while not written.done():
        await pace.after(await host.agent.tick() is not None)
    await written
    fetched = asyncio.ensure_future(
        runner.run(workspace, command(epoch, "git", "fetch", INCOMING), seal=NO_SEAL)
    )
    await claims(host.agent, fetched)

    assert (await fetched).exit_code == 0
    assert host.setup.ran == [*SETUP, INCOMING], "the setup ran once, at the build"
    kept = kept_base(host, api).read_bytes()
    assert host.twin.started_from[agent_session_id] == hashlib.sha256(kept).hexdigest()


async def test_the_setup_on_a_host_is_given_no_secret_and_no_credential_of_the_hosts(
    api: Stack, tmp_path: Path
) -> None:
    exec_relay = api.container.managers.exec_relay
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    host = await a_host(api, pool.id, tmp_path)

    assert await exec_relay.ask_prepare(api.owner, agent_session_id, ON_BASE)
    await host.claimed()

    assert host.setup.ran == list(SETUP)
    assert host.setup.envs == [{}, {}], "no variable of its own"
    credential = host.agent.credential.token
    for held in (SECRET, credential):
        assert not any(held in command for command in host.setup.ran)
        assert held.encode() not in kept_base(host, api).read_bytes()


async def test_a_base_that_holds_a_hosts_secret_is_not_kept_and_the_prepare_is_unbuilt(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    host = await a_host(api, pool.id, tmp_path)
    host.twin.writes = f"export TOKEN={SECRET}\n".encode()

    assert await managers.exec_relay.ask_prepare(api.owner, agent_session_id, ON_BASE)
    await host.claimed()

    assert not kept_base(host, api).exists()
    row = await managers.work.latest_for_target(
        api.owner, PlacementWorkKind.WORKSPACE, agent_session_id
    )
    assert row is not None and "SERVICE_TOKEN" in (row.last_error or "")
    assert SECRET not in (row.last_error or "")
    assert await managers.exec_relay.binding_of(api.owner, agent_session_id) is None


async def test_an_owner_who_closed_egress_refuses_a_base_whose_setup_reaches_out(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    host = await a_host(api, pool.id, tmp_path, egress=frozenset())

    assert await managers.exec_relay.ask_prepare(api.owner, agent_session_id, ON_BASE)
    await host.claimed()

    assert host.setup.ran == [], "nothing ran"
    assert not kept_base(host, api).exists()
    assert await managers.exec_relay.binding_of(api.owner, agent_session_id) is None
