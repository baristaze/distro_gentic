"""An agent project's workspace base as the platform serves it, over the memory roots,
the twin provider, the twin transport, and the local buckets. A kind that
takes its agent project's workspace base, the platform's or one a product's slot
names, pins the base the workspace base names when its session is created; a
kind that does not, and an agent project that names none, pin what they pinned
before. The first session builds the base and
the next one starts from it. A changed setup command builds a new base for
the sessions created after it, and a session already running keeps the
base it started on. A setup that fails ends the loop with the command and
its exit code, and keeps no base. A setup is given no secret and nothing
of the tenant's records."""

import hashlib
import logging
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

import pytest
from contracts.agent_workspaces import AgentProjectsTwin
from contracts.loops import ASSISTANT, reply, said
from contracts.platform_loops import PlatformLoop, platform_loop_over

from acme.infra.buckets import Buckets
from acme.infra.impl.local import InfraLocalImpl
from acme.infra.transports import CommandSpec
from acme.infra.transports.twin import TransportTwinImpl, TwinReply
from acme.infra.workspaces import (
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
    Workspace,
    WorkspaceBase,
    WorkspaceProviderInterface,
)
from acme.infra.workspaces.twin import WorkspaceTwinImpl
from acme.om.agent_projects.types.agent_project import AgentWorkspaceBase
from acme.om.platform_agents.kinds import SOFTWARE_ENGINEER, WORKSPACE_BASE_KINDS
from acme.om.platform_root import PlatformRootOptions, ProductKinds
from acme.om.steps.types.header import LoopOutcome
from acme.om.tools.impl.bases import BUCKET, PREFIX, base_key

NONE = EgressPolicy(mode=EgressMode.NONE)
SEALED = IsolationSpec(mode=IsolationMode.TWIN, egress=NONE)
TAKES = ASSISTANT.model_copy(update={"name": SOFTWARE_ENGINEER, "version": 8, "isolation": SEALED})
"""A kind the platform names among those that take their agent project's
workspace_base: the software engineer at version 8, here with the assistant's loop on
the twin."""
OWN = ASSISTANT.model_copy(update={"isolation": SEALED})
"""A kind that keeps its own base: none."""
BUILDER = ASSISTANT.model_copy(update={"name": "builder", "version": 2, "isolation": SEALED})
"""A product's kind its slot names among those that take their agent project's
workspace_base."""
READER = ASSISTANT.model_copy(update={"name": "reader", "isolation": SEALED})
"""A product's kind its slot does not name."""
PRODUCT = ProductKinds(agents=(BUILDER, READER), workspace_bases=frozenset({("builder", 2)}))

WORKSPACE_BASE = AgentWorkspaceBase(
    image="python:3.14-slim",
    setup=("pip install acme-tools", "echo built >> /opt/count"),
    registries=("pypi.org", "files.pythonhosted.org"),
)
CHANGED = WORKSPACE_BASE.model_copy(
    update={"setup": ("pip install acme-tools", "echo changed >> /opt/count")}
)
TOKEN = "tok-0123456789abcdef"


class Setup:
    """The twin transport's handler: each command it runs, the workspace base
    it gets, and the exit code a case asks of a command."""

    def __init__(self) -> None:
        self.ran: list[str] = []
        self.envs: list[Mapping[str, str]] = []
        self.exits: dict[str, int] = {}

    async def __call__(self, command: CommandSpec, env: Mapping[str, str]) -> TwinReply:
        self.ran.append(command.argv[-1])
        self.envs.append(dict(env))
        return TwinReply(exit_code=self.exits.get(command.argv[-1], 0))


class BuiltTwin(WorkspaceTwinImpl):
    """The twin provider: a snapshot of a workspace holds each command its
    transport ran there, so a base holds its setup. The hash of the base
    each workspace started from is kept, by workspace."""

    def __init__(self, transport: TransportTwinImpl) -> None:
        super().__init__()
        self._transport = transport
        self.started_from: dict[UUID, list[str]] = {}

    async def prepare(
        self,
        org_id: UUID,
        workspace_id: UUID,
        spec: IsolationSpec,
        snapshot: bytes | None = None,
        base: bytes | None = None,
        *,
        building: bool = False,
    ) -> Workspace:
        if base is not None:
            started = self.started_from.setdefault(workspace_id, [])
            started.append(hashlib.sha256(base).hexdigest())
        return await super().prepare(org_id, workspace_id, spec, snapshot, base, building=building)

    async def snapshot(self, workspace: Workspace) -> bytes:
        ran = [
            command.argv[-1]
            for command in self._transport.commands
            if (workspace.id, command.key) in self._transport.records
        ]
        return await super().snapshot(workspace) + "\n".join(ran).encode()


class InfraBuilt(InfraLocalImpl):
    def __init__(self, root: Path, setup: Setup) -> None:
        super().__init__(root)
        transport = self.get_transport()
        assert isinstance(transport, TransportTwinImpl)
        transport.handler = setup
        self.built = BuiltTwin(transport)

    def get_workspaces(self) -> WorkspaceProviderInterface:
        return self.built


class WorkspaceBases:
    """A tenant whose sessions belong to one agent project, over the built twin."""

    def __init__(self, tmp_path: Path, product: ProductKinds | None = None) -> None:
        self.setup = Setup()
        self.infra = InfraBuilt(tmp_path, self.setup)
        self.agent_projects = AgentProjectsTwin(repository=None)
        self.loop: PlatformLoop = platform_loop_over(
            tmp_path,
            kinds=(TAKES, OWN),
            infra=self.infra,
            platform=PlatformRootOptions(
                workspace_agent_projects=self.agent_projects, product_kinds=product
            ),
        )

    async def run(self, session_id: UUID) -> LoopOutcome | None:
        await self.loop.say(session_id, "Check the report.")
        self.loop.anthropic.add(reply(said("Checked.")))
        return (await self.loop.loops.run(self.loop.owner, session_id)).outcome

    async def pinned(self, session_id: UUID) -> WorkspaceBase | None:
        return (
            await self.loop.platform.agent_workspaces.get_workspace(self.loop.owner, session_id)
        ).base

    async def kept(self) -> list[str]:
        buckets = self.infra.get_buckets()
        return sorted(await buckets.list(self.loop.owner.org_id, BUCKET, PREFIX, 100))

    async def held(self, base: WorkspaceBase) -> str:
        """The hash of the base the store keeps for `base`."""
        buckets = self.infra.get_buckets()
        data = await buckets.get(self.loop.owner.org_id, Buckets.SNAPSHOTS, key(base))
        return hashlib.sha256(data).hexdigest()


def key(base: WorkspaceBase) -> str:
    return base_key(SEALED.model_copy(update={"base": base}))


@pytest.fixture
def workspace_bases(tmp_path: Path) -> WorkspaceBases:
    return WorkspaceBases(tmp_path)


def test_the_software_engineer_from_version_8_takes_its_agent_projects_workspace_base() -> None:
    assert (SOFTWARE_ENGINEER, 8) in WORKSPACE_BASE_KINDS
    assert all(name != SOFTWARE_ENGINEER or version >= 8 for name, version in WORKSPACE_BASE_KINDS)


def test_a_workspace_base_names_a_setup_whose_egress_follows_its_registries() -> None:
    """A setup that names a registry runs with open egress, the agent project's
    recorded choice; one that names none reaches nothing. Registries serve
    a setup, and an image never reads as an option."""
    assert WORKSPACE_BASE.base() == WorkspaceBase(
        image=WORKSPACE_BASE.image,
        setup=WORKSPACE_BASE.setup,
        egress=EgressPolicy(mode=EgressMode.OPEN),
    )
    sealed = WORKSPACE_BASE.model_copy(update={"registries": ()})
    assert sealed.base().egress.mode is EgressMode.NONE
    with pytest.raises(ValueError, match="registries only for a setup"):
        AgentWorkspaceBase(image="python:3.14-slim", registries=("pypi.org",))
    with pytest.raises(ValueError, match="each registry once"):
        AgentWorkspaceBase(image="python:3.14-slim", setup=("true",), registries=("a.io", "a.io"))
    for image in ("--privileged", "-v/:/host", "python 3", ""):
        with pytest.raises(ValueError):
            AgentWorkspaceBase(image=image)


async def test_a_kind_that_takes_its_agent_projects_workspace_base_pins_its_base(
    workspace_bases: WorkspaceBases,
) -> None:
    """The kind that takes it pins the base it names; a kind that does
    not keeps its own, and an agent project that names none changes nothing."""
    loop = workspace_bases.loop
    bare = await loop.start(TAKES.name)
    workspace_bases.agent_projects.workspace_base = WORKSPACE_BASE.base()
    takes = await loop.start(TAKES.name)
    own = await loop.start(OWN.name)

    assert await workspace_bases.pinned(takes) == WORKSPACE_BASE.base()
    assert await workspace_bases.pinned(own) is None, "its kind keeps its own"
    assert await workspace_bases.pinned(bare) is None, (
        "its agent project named none when it was created"
    )
    pinned = await loop.platform.agent_workspaces.get_workspace(loop.owner, takes)
    assert pinned.egress is EgressMode.NONE, "its workspace keeps its kind's egress"


async def test_a_products_kind_its_slot_names_pins_its_agent_projects_workspace_base(
    tmp_path: Path,
) -> None:
    """The root reads the product's kinds beside the platform's: the one its
    slot names pins the base it names, as the software engineer does, and the
    one it does not keeps its own."""
    workspace_bases = WorkspaceBases(tmp_path, PRODUCT)
    workspace_bases.agent_projects.workspace_base = WORKSPACE_BASE.base()
    builder = await workspace_bases.loop.start(BUILDER.name)
    reader = await workspace_bases.loop.start(READER.name)
    software_engineer = await workspace_bases.loop.start(TAKES.name)

    assert await workspace_bases.pinned(builder) == WORKSPACE_BASE.base()
    assert await workspace_bases.pinned(reader) is None, "its slot does not name it"
    assert await workspace_bases.pinned(software_engineer) == WORKSPACE_BASE.base(), (
        "the platform's too"
    )


def test_a_slot_names_only_the_products_own_kinds_at_a_version_it_declares() -> None:
    """A product never makes one of the platform's kinds take it, nor a
    version of its own it does not declare."""
    for named in ((SOFTWARE_ENGINEER, 7), ("builder", 1), ("absent", 1)):
        with pytest.raises(ValueError, match="no agent kind of the product's"):
            ProductKinds(agents=(BUILDER,), workspace_bases=frozenset({named}))


async def test_one_build_serves_the_agent_project_and_the_next_session_runs_no_setup(
    workspace_bases: WorkspaceBases,
) -> None:
    workspace_bases.agent_projects.workspace_base = WORKSPACE_BASE.base()
    first = await workspace_bases.loop.start(TAKES.name)
    second = await workspace_bases.loop.start(TAKES.name)

    assert await workspace_bases.run(first) is LoopOutcome.SUCCEEDED
    assert workspace_bases.setup.ran == list(WORKSPACE_BASE.setup), "the first session built it"
    assert await workspace_bases.run(second) is LoopOutcome.SUCCEEDED

    assert workspace_bases.setup.ran == list(WORKSPACE_BASE.setup), "the second ran no setup"
    started = workspace_bases.infra.built.started_from
    assert started[first] == started[second] == [await workspace_bases.held(WORKSPACE_BASE.base())]
    assert await workspace_bases.kept() == [key(WORKSPACE_BASE.base())]


async def test_a_changed_setup_command_builds_a_new_base_and_a_running_session_keeps_its_own(
    workspace_bases: WorkspaceBases,
) -> None:
    workspace_bases.agent_projects.workspace_base = WORKSPACE_BASE.base()
    running = await workspace_bases.loop.start(TAKES.name)
    assert await workspace_bases.run(running) is LoopOutcome.SUCCEEDED

    workspace_bases.agent_projects.workspace_base = CHANGED.base()
    later = await workspace_bases.loop.start(TAKES.name)
    assert await workspace_bases.run(later) is LoopOutcome.SUCCEEDED
    assert await workspace_bases.run(running) is LoopOutcome.SUCCEEDED

    assert workspace_bases.setup.ran == [*WORKSPACE_BASE.setup, *CHANGED.setup], "built once each"
    assert await workspace_bases.pinned(running) == WORKSPACE_BASE.base()
    assert await workspace_bases.pinned(later) == CHANGED.base()
    started = workspace_bases.infra.built.started_from
    first = await workspace_bases.held(WORKSPACE_BASE.base())
    assert started[running] == [first, first], "each of its loops starts from the base it pinned"
    assert started[later] == [await workspace_bases.held(CHANGED.base())] != [first]
    assert await workspace_bases.kept() == sorted([key(WORKSPACE_BASE.base()), key(CHANGED.base())])


async def test_a_failed_setup_ends_the_loop_with_the_command_and_its_exit_code_and_keeps_no_base(
    workspace_bases: WorkspaceBases, caplog: pytest.LogCaptureFixture
) -> None:
    workspace_bases.agent_projects.workspace_base = WORKSPACE_BASE.base()
    workspace_bases.setup.exits["pip install acme-tools"] = 1
    session_id = await workspace_bases.loop.start(TAKES.name)

    with caplog.at_level(logging.WARNING):
        assert await workspace_bases.run(session_id) is LoopOutcome.ERRORED

    told = " ".join(record.getMessage() for record in caplog.records)
    assert "the base's setup command 1, 'pip install acme-tools', exited 1" in told
    assert await workspace_bases.kept() == [], "no half-built base"
    assert workspace_bases.infra.built.started_from == {}, "no workspace started from one"


async def test_the_setup_is_given_no_secret_and_nothing_of_the_tenants_records(
    workspace_bases: WorkspaceBases,
) -> None:
    """The setup's commands carry the workspace base's text alone, and run with
    no variable of their own: not the tenant's secret, nor the session's
    words, nor the agent project."""
    loop = workspace_bases.loop
    await workspace_bases.infra.get_secrets().put(loop.owner.org_id, "SERVICE_TOKEN", TOKEN)
    workspace_bases.agent_projects.workspace_base = WORKSPACE_BASE.base()
    session_id = await loop.start(TAKES.name)

    assert await workspace_bases.run(session_id) is LoopOutcome.SUCCEEDED

    assert workspace_bases.setup.ran == list(WORKSPACE_BASE.setup)
    assert workspace_bases.setup.envs == [{}, {}], "no variable of its own"
    for held in (TOKEN, "Check the report.", str(workspace_bases.agent_projects.agent_project_id)):
        assert not any(held in command for command in workspace_bases.setup.ran)
