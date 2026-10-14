"""The runner's composition ends every success through the evidence's
gate, over the work product the product wires, or the workspaces' read of
the checkout, and boots outside `local` with it; outside `local`, it refuses
every port that would ship a gate open."""

import re
from pathlib import Path

import pytest
from contracts.doubles import context
from contracts.factories import make_org
from contracts.ports import open_ports

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.workspaces import EgressMode, IsolationMode, WorkspaceBase
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.om.agent_playbooks.impl.agents import AgentsManagerKindManualImpl
from acme.om.agent_workspaces.impl.executor import ExecutorAgentWorkspacesImpl, Pin
from acme.om.agent_workspaces.impl.work_product import WorkProductAgentWorkspacesImpl
from acme.om.agent_workspaces.types.workspace import AgentSessionWorkspace
from acme.om.agents.impl.manager import AgentsManagerImpl
from acme.om.base import new_id, utcnow
from acme.om.context import Role
from acme.om.evidence import WorkProductInterface
from acme.om.evidence.impl.gate import ResultGateEvidenceImpl
from acme.om.evidence.impl.manager import EvidenceManagerImpl
from acme.om.evidence.impl.ports import WorkProductMemoryImpl
from acme.om.exceptions import UnsafeConfiguration
from acme.om.root import PlatformPorts
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.workers.session_runner.container import RunnerContainer
from acme.workers.session_runner.settings import SessionRunnerSettings


def runner(
    tmp_path: Path,
    work_product: WorkProductInterface | None = None,
    *,
    storage: StorageMemoryImpl | None = None,
    ports: PlatformPorts | None = None,
    image: str | None = None,
) -> RunnerContainer:
    named = {} if image is None else {"workspace_image": image}
    settings = SessionRunnerSettings.model_validate(
        {"_env_file": None, "environment": "staging", "runner_id": "runner-test", **named}
    )
    return RunnerContainer.over(
        settings,
        storage or StorageMemoryImpl(),
        InfraLocalImpl(tmp_path),
        IntegrationsOverImpl(IdentityProviderAbsentImpl(), scripted_model_providers()),
        ports=ports or PlatformPorts(work_product=work_product),
    )


def test_the_runner_outside_local_refuses_every_port_that_ships_a_gate_open(
    tmp_path: Path,
) -> None:
    storage = StorageMemoryImpl()
    for named, ports in open_ports(storage):
        with pytest.raises(UnsafeConfiguration, match=re.escape(named)):
            runner(tmp_path, storage=storage, ports=ports)


def test_the_runners_container_builds_the_evidence_gate(tmp_path: Path) -> None:
    work = WorkProductMemoryImpl()
    for container, reads in (
        (runner(tmp_path, work_product=work), WorkProductMemoryImpl),
        (runner(tmp_path), WorkProductAgentWorkspacesImpl),
    ):
        # Each session is made with its kind manual, by the engine's agents.
        kind_manual = container.managers.agents
        assert isinstance(kind_manual, AgentsManagerKindManualImpl)
        agents = kind_manual._inner  # pyright: ignore[reportPrivateUsage]
        assert isinstance(agents, AgentsManagerImpl)
        gate = agents._gate  # pyright: ignore[reportPrivateUsage]
        assert isinstance(gate, ResultGateEvidenceImpl)
        assert isinstance(gate._work_product, reads)  # pyright: ignore[reportPrivateUsage]


def test_the_runners_executor_records_the_image_its_workspaces_run(tmp_path: Path) -> None:
    container = runner(tmp_path, image="registry.example/checks:2")

    evidence = container.managers.evidence
    assert isinstance(evidence, EvidenceManagerImpl)
    executor = evidence._executors.platform  # pyright: ignore[reportPrivateUsage]
    assert isinstance(executor, ExecutorAgentWorkspacesImpl)
    assert executor._options.image == "registry.example/checks:2"  # pyright: ignore[reportPrivateUsage]


async def test_the_runners_executor_reads_the_base_a_session_of_the_cloud_pinned(
    tmp_path: Path,
) -> None:
    storage = StorageMemoryImpl()
    container = runner(tmp_path, storage=storage)
    evidence = container.managers.evidence
    assert isinstance(evidence, EvidenceManagerImpl)
    executor = evidence._executors.platform  # pyright: ignore[reportPrivateUsage]
    assert isinstance(executor, ExecutorAgentWorkspacesImpl)
    assert executor._bases is not None, "a base with setup is read, never refused"  # pyright: ignore[reportPrivateUsage]
    ctx = context(Role.OWNER, make_org())
    now = utcnow()
    pinned = AgentSessionWorkspace(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        agent_project_id=new_id(),
        level=IsolationMode.CONTAINER,
        egress=EgressMode.NONE,
        egress_source="its kind's",
        base=WorkspaceBase(image="registry.example/toolchain:3", setup=("make deps",)),
        branch="sessions/one",
    )
    await storage.get_agent_workspace_storage().create_workspace(ctx.org_id, pinned)

    read = executor._pinned  # pyright: ignore[reportPrivateUsage]
    assert await read(ctx, pinned.id) == Pin(pinned.spec(), walled=False)
    assert await read(ctx, new_id()) is None, "a session that pinned none runs as before"
