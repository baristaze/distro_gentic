"""A fork of a workspace a customer's host holds, over Postgres, as the
session runner and a host of the pool run it: the runner's container, and
the host's own agent against the API in process, each over a storage root
of its own, and one key service.

A parent on the host writes a file and forks in the same run. The host
snapshots the live workspace and keeps the copy in its own store as the
child's; the platform records where it lives, never its bytes, and nothing
reaches the platform's bucket. The child's first prepare restores the copy
on a host of the same pool, and it reads the parent's file there; what the
child writes never reaches the parent's workspace. A host that cannot take
a snapshot of the workspace refuses the fork with its reason, and a session
that keeps no content at rest is refused before any host is asked: each
before the tree's slot is taken or the child is made.

Needs a migrated database (`make migrate`); the fork's case needs a local
Docker as well."""

import asyncio
from collections.abc import AsyncIterator, Coroutine
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from host_support import Stack, directory_host, docker_runs, postgres, probes, stack
from runner_support import HOST, TOOLS, answers, assistant, runs

from acme.apps.host.agent import HostAgent
from acme.apps.host.ceilings import Ceilings
from acme.apps.host.config import DEFAULT_IMAGE
from acme.apps.host.exec_relay import ExecutorRelayImpl
from acme.apps.host.main import host_transports, host_workspaces
from acme.apps.host.snapshots import HostSnapshots
from acme.client.types import IsolationMode as HostMode
from acme.infra.agent_workspaces import (
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
)
from acme.infra.agent_workspaces.container import AgentWorkspaceContainerImpl
from acme.infra.buckets import Buckets
from acme.infra.transports.broker import BrokerNullImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.calls import ModelReply
from acme.integrations.model_providers.content import TextBlock, ToolUseBlock
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import ProviderName, StopReason, Usage
from acme.om.agent_steps.rules import message_step
from acme.om.agent_steps.types.agent_step import AgentStep, AgentStepType
from acme.om.agent_steps.types.header import (
    ControlCommand,
    ControlHeader,
    LoopOutcome,
    ToolFailure,
    ToolRequestHeader,
    ToolResponseHeader,
)
from acme.om.agents.types.kind import AgentKind, TreeLimits
from acme.om.agents.types.request import Start
from acme.om.agents.types.run import LoopRun, RunEnd
from acme.om.base import new_id, utcnow
from acme.om.exceptions import NotFound
from acme.om.placement.kinds import PlacementWorkKind
from acme.om.platform_root import PlatformPorts, ProductKinds
from acme.om.privacy.types.agent_session_privacy import StorageMode, StoragePolicy
from acme.om.spend_budgets.types.amount import Amount
from acme.om.tools.impl.snapshots import session_prefix
from acme.om.tools.native.spawn_sub_agent import SPAWN_SUB_AGENT
from acme.om.tools.types.policy import Decision, ToolPolicyLayer, ToolPolicyRule
from acme.om.tools.types.tool import ToolClass
from acme.services.api.seed import seed_platform
from acme.workers.agent_session_runner.container import RunnerContainer
from acme.workers.agent_session_runner.settings import AgentSessionRunnerSettings

pytestmark = pytest.mark.integration

SEALED = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))
"""A container that lets nothing leave, kept as a cache: a fork needs no
snapshot durability, only a provider that takes one."""


def forker(isolation: IsolationSpec) -> AgentKind:
    """The runner suite's assistant that may also start a sub-agent, of its
    own kind, in a copy of its workspace."""
    return assistant(isolation).model_copy(
        update={
            "name": "forker",
            "tools": ("run_command", SPAWN_SUB_AGENT),
            "tree": TreeLimits(height=2, count=2),
            "share": Amount(tokens=1_000_000),
            "policy": ToolPolicyLayer(
                rules=tuple(
                    ToolPolicyRule(authorization_class=kind, decision=Decision.ALLOW)
                    for kind in (ToolClass.EXECUTE, ToolClass.SPAWN)
                )
            ),
        }
    )


KIND = forker(SEALED)
ON_A_DIRECTORY = forker(HOST)

SETTINGS = AgentSessionRunnerSettings.model_validate(
    {"_env_file": None, "environment": "test", "runner_id": "runner-fork"}
)


def forks() -> ModelReply:
    """A turn that starts a sub-agent in a copy of the workspace."""
    use = ToolUseBlock(
        id=f"use_{uuid4().hex[:12]}",
        name=SPAWN_SUB_AGENT,
        input={"title": "a try", "objective": "Read the note and try it.", "fork": True},
    )
    return ModelReply(
        blocks=(TextBlock(text="I fork a try."), use),
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(input=120, output=30),
        model="claude-sonnet-5-5",
    )


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[Stack]:
    storage = postgres()
    async with stack(tmp_path / "api", storage) as running:
        yield running
    await storage.close()


def runner_over(api: Stack, kind: AgentKind) -> RunnerContainer:
    return RunnerContainer.over(
        SETTINGS,
        postgres(),
        api.container.infra,
        IntegrationsOverImpl(IdentityProviderAbsentImpl(), scripted_model_providers()),
        ports=PlatformPorts(kinds=ProductKinds(agents=(kind,), tools=lambda _: TOOLS)),
    )


async def container_host_keeping(api: Stack, pool_id: UUID, where: Path) -> tuple[HostAgent, Path]:
    """A host of the pool as the host's `main` wires one: a container per
    workspace on the local Docker, of the default image, and a store of
    its own that keeps their snapshots, which its probe showed. Its
    ceilings take any agent project, and let nothing leave."""
    settings = replace(
        api.settings(where / "home", None), enrollment_token=await api.token(pool_id)
    )
    store = HostSnapshots(settings.snapshots_path, settings.secrets_path)
    broker = BrokerNullImpl()
    agents: list[HostAgent] = []
    executor = ExecutorRelayImpl(
        lambda: agents[0].client(),
        host_transports(settings, broker),
        host_workspaces(settings),
        snapshots=store,
        broker=broker,
        snapshot_modes=lambda: frozenset({IsolationMode.CONTAINER}),
        flush_seconds=0.0,
        renew_seconds=0.2,
    )
    checks = replace(probes(HostMode.container), snapshots={HostMode.container: store.usable})
    host = HostAgent(
        settings,
        Ceilings(agent_projects=None, min_isolation=HostMode.container, egress=frozenset()),
        checks,
        api.client,
        executor,
    )
    agents.append(host)
    await host.start()
    return host, settings.snapshots_path


async def driven(host: HostAgent, work: Coroutine[Any, Any, LoopRun]) -> LoopRun:
    """`work` run while the host claims what it asks of it."""
    running = asyncio.ensure_future(work)
    while not running.done():
        if await host.claim_once() is None:
            await asyncio.sleep(0.01)
    return await running


async def steps_of(runner: RunnerContainer, owner: Any, agent_session_id: UUID) -> list[AgentStep]:
    page = await runner.managers.agent_steps.get_agent_steps(owner, agent_session_id, 0, 200)
    return list(page.items)


def outputs(steps: list[AgentStep]) -> list[str]:
    """What each call answered, in order."""
    return [
        step.as_tool_response().parts[0].text  # type: ignore[union-attr]
        for step in steps
        if step.type is AgentStepType.TOOL_RESPONSE
    ]


def spawn_of(steps: list[AgentStep]) -> tuple[AgentStep, AgentStep]:
    """The one spawn call and its answer: the child's id is the call's."""
    (request,) = [
        step
        for step in steps
        if isinstance(step.header, ToolRequestHeader) and step.header.tool == SPAWN_SUB_AGENT
    ]
    (answer,) = [step for step in steps if step.responds_to == request.id]
    return request, answer


@pytest.mark.skipif(not docker_runs(), reason="needs a local Docker")
async def test_a_hosted_parent_forks_and_its_child_reads_the_copy_its_host_keeps(
    api: Stack, tmp_path: Path
) -> None:
    runner = runner_over(api, KIND)
    owner, managers = api.owner, runner.managers
    await seed_platform(runner.storage, managers, owner, (KIND,))
    model = runner.integrations.get_model_providers().get(ProviderName.ANTHROPIC)
    assert isinstance(model, ModelProviderScriptedImpl)
    pool = await api.pool("pool-a")
    host, store = await container_host_keeping(api, pool.id, tmp_path / "host")
    session = await managers.agents.start_agent_session(
        owner, Start(id=new_id(), kind=KIND.name, title="a hypothesis")
    )
    parent = session.id
    await api.container.managers.hosts.place_session(owner, parent, pool.id)
    said = message_step(new_id(), utcnow(), parent, owner, "Write the note, then fork.")
    await managers.agent_sessions.receive(owner, parent, [said])
    child: UUID | None = None
    try:
        # The first loop asks a host of the pool for the workspace and
        # parks; the host makes the container, and the session is bound.
        parked = await managers.loop.run(owner, parent)
        assert parked.end is RunEnd.PARKED and parked.park is not None
        assert await host.claim_once() is not None
        await host.idle()
        assert await managers.exec_relay.binding_of(owner, parent) is not None

        # The parent writes a file and forks in the same run.
        await managers.agent_sessions.wake_agent_session(owner, parent, parked.park)
        model.add(runs("sh", "-c", "echo from-the-parent > note"))
        model.add(forks())
        model.add(answers("Forked."))
        ended = await driven(host, managers.loop.run(owner, parent))
        assert ended.outcome is LoopOutcome.SUCCEEDED, ended
        history = await steps_of(runner, owner, parent)
        request, spawned = spawn_of(history)
        header = spawned.header
        assert isinstance(header, ToolResponseHeader) and header.failure is None, outputs(history)
        assert not [s for s in history if s.type is AgentStepType.SNAPSHOTTED], (
            "the parent keeps none"
        )
        child = request.id

        # The child starts from its own copy, which the host keeps as the child's.
        restore = next(
            step.header
            for step in await steps_of(runner, owner, child)
            if isinstance(step.header, ControlHeader)
            and step.header.command is ControlCommand.RESTORE
        )
        assert restore.snapshot is not None
        record = await managers.agent_workspaces.kept_snapshot(owner, restore.snapshot.id)
        assert record is not None and record.on_host and record.agent_session_id == child
        assert (record.pool_id, record.host_id) == (pool.id, UUID(host.credential.claimant_id))
        kept = store / record.reference
        assert kept.is_relative_to(store / str(owner.org_id) / str(child)), "kept as the child's"
        assert kept.stat().st_size == record.size

        # Its first prepare restores the copy on the pool's host, and the
        # child reads the parent's file; what it writes stays its own.
        model.add(runs("cat", "note"))
        model.add(runs("sh", "-c", "echo from-the-child > theirs"))
        model.add(answers("Read it."))
        tried = await driven(host, managers.loop.run(owner, child))
        assert tried.outcome is LoopOutcome.SUCCEEDED, tried
        read, _ = outputs(await steps_of(runner, owner, child))
        assert "from-the-parent" in read
        holder = await managers.exec_relay.binding_of(owner, child)
        assert holder is not None and holder.host_id == UUID(host.credential.claimant_id)

        asked = message_step(new_id(), utcnow(), parent, owner, "What does the workspace hold?")
        await managers.agent_sessions.receive(owner, parent, [asked])
        model.add(runs("ls"))
        model.add(answers("The note."))
        again = await driven(host, managers.loop.run(owner, parent))
        assert again.outcome is LoopOutcome.SUCCEEDED, again
        listed = outputs(await steps_of(runner, owner, parent))[-1]
        assert "note" in listed and "theirs" not in listed, "the child's writes never reach it"

        # Nothing of either workspace reached the platform's bucket.
        buckets = api.container.infra.get_buckets()
        for agent_session_id in (parent, child):
            prefix = session_prefix(agent_session_id)
            assert await buckets.list(owner.org_id, Buckets.SNAPSHOTS, prefix, 10) == []
    finally:
        provider = AgentWorkspaceContainerImpl(DEFAULT_IMAGE, timedelta(seconds=30), "purge")
        for agent_session_id in (parent, child):
            if agent_session_id is not None:
                await provider.purge(owner.org_id, agent_session_id)
        await runner.storage.close()


@pytest.mark.parametrize(
    ("memory_only", "reason"),
    [
        # A bare directory's commands write outside it, so its host takes
        # no snapshot of it, and says so.
        (False, "has not probed snapshots of a host workspace"),
        # A session that keeps no content at rest puts no copy at rest: no
        # host is asked.
        (True, "keeps no content at rest"),
    ],
)
async def test_a_fork_refused_by_its_host_or_its_session_spends_nothing(
    api: Stack, tmp_path: Path, memory_only: bool, reason: str
) -> None:
    runner = runner_over(api, ON_A_DIRECTORY)
    owner, managers = api.owner, runner.managers
    await seed_platform(runner.storage, managers, owner, (ON_A_DIRECTORY,))
    model = runner.integrations.get_model_providers().get(ProviderName.ANTHROPIC)
    assert isinstance(model, ModelProviderScriptedImpl)
    pool = await api.pool("pool-a")
    host, _ = await directory_host(api, pool.id, tmp_path / "host")
    session = await managers.agents.start_agent_session(
        owner, Start(id=new_id(), kind=ON_A_DIRECTORY.name, title="a hypothesis")
    )
    parent = session.id
    await api.container.managers.hosts.place_session(owner, parent, pool.id)
    if memory_only:
        policy = StoragePolicy(mode=StorageMode.MEMORY_ONLY, keep_shape=False)
        await managers.privacy.set_policy(owner, parent, policy)
    said = message_step(new_id(), utcnow(), parent, owner, "Write the note, then fork.")
    await managers.agent_sessions.receive(owner, parent, [said])
    try:
        parked = await managers.loop.run(owner, parent)
        assert parked.end is RunEnd.PARKED and parked.park is not None
        assert await host.claim_once() is not None
        await host.idle()
        before = (await managers.agents.tree_of(owner, parent)).size

        await managers.agent_sessions.wake_agent_session(owner, parent, parked.park)
        model.add(runs("sh", "-c", "echo from-the-parent > note"))
        model.add(forks())
        model.add(answers("Refused."))
        ended = await driven(host, managers.loop.run(owner, parent))

        assert ended.outcome is LoopOutcome.SUCCEEDED, ended
        request, refused = spawn_of(await steps_of(runner, owner, parent))
        header = refused.header
        assert isinstance(header, ToolResponseHeader) and header.failure is ToolFailure.PERMANENT
        text = outputs([refused])[0]
        assert reason in text, text
        assert (await managers.agents.tree_of(owner, parent)).size == before, "no slot taken"
        with pytest.raises(NotFound):
            await managers.agent_sessions.get_agent_session(owner, request.id)
        assert await managers.agent_workspaces.kept_snapshots(owner, request.id) == ()
        assert await managers.agent_workspaces.kept_snapshots(owner, parent) == ()
        latest = await managers.work.latest_for_target(owner, PlacementWorkKind.WORKSPACE, parent)
        assert latest is not None
        asked = latest.payload["operation"]
        assert asked == ("prepare" if memory_only else "snapshot"), asked
    finally:
        await runner.storage.close()
