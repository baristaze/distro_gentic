"""A project's environment as the platform serves it, over the memory roots,
the twin provider, the twin transport, and the local buckets. A kind that
takes its project's environment pins the base the environment names when
its session is created; a kind that does not, and a project that names
none, pin what they pinned before. The first session builds the base and
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
from contracts.loops import ASSISTANT, Loop, loop_over, reply, said
from contracts.workspaces import ProjectsTwin

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
from acme.om.platform_agents.kinds import ENGINEER, ENVIRONMENT_KINDS
from acme.om.projects.types.project import ProjectEnvironment
from acme.om.steps.types.header import LoopOutcome
from acme.om.tools.impl.bases import BUCKET, PREFIX, base_key

NONE = EgressPolicy(mode=EgressMode.NONE)
SEALED = IsolationSpec(mode=IsolationMode.TWIN, egress=NONE)
TAKES = ASSISTANT.model_copy(update={"name": ENGINEER, "version": 8, "isolation": SEALED})
"""A kind the platform names among those that take their project's
environment: the engineer at version 8, here with the assistant's loop on
the twin."""
OWN = ASSISTANT.model_copy(update={"isolation": SEALED})
"""A kind that keeps its own base: none."""

ENVIRONMENT = ProjectEnvironment(
    image="python:3.14-slim",
    setup=("pip install acme-tools", "echo built >> /opt/count"),
    registries=("pypi.org", "files.pythonhosted.org"),
)
CHANGED = ENVIRONMENT.model_copy(
    update={"setup": ("pip install acme-tools", "echo changed >> /opt/count")}
)
TOKEN = "tok-0123456789abcdef"


class Setup:
    """The twin transport's handler: each command it runs, the environment
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


class Environments:
    """A tenant whose sessions belong to one project, over the built twin."""

    def __init__(self, tmp_path: Path) -> None:
        self.setup = Setup()
        self.infra = InfraBuilt(tmp_path, self.setup)
        self.projects = ProjectsTwin(repository=None)
        self.loop: Loop = loop_over(
            tmp_path, kinds=(TAKES, OWN), infra=self.infra, workspace_projects=self.projects
        )

    async def run(self, session_id: UUID) -> LoopOutcome | None:
        await self.loop.say(session_id, "Check the report.")
        self.loop.anthropic.add(reply(said("Checked.")))
        return (await self.loop.loops.run(self.loop.owner, session_id)).outcome

    async def pinned(self, session_id: UUID) -> WorkspaceBase | None:
        return (await self.loop.managers.workspaces.get_workspace(self.loop.owner, session_id)).base

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
def environments(tmp_path: Path) -> Environments:
    return Environments(tmp_path)


def test_the_engineer_from_version_8_takes_its_projects_environment() -> None:
    assert (ENGINEER, 8) in ENVIRONMENT_KINDS
    assert all(name != ENGINEER or version >= 8 for name, version in ENVIRONMENT_KINDS)


def test_an_environment_names_a_setup_whose_egress_follows_its_registries() -> None:
    """A setup that names a registry runs with open egress, the project's
    recorded choice; one that names none reaches nothing. Registries serve
    a setup, and an image never reads as an option."""
    assert ENVIRONMENT.base() == WorkspaceBase(
        image=ENVIRONMENT.image, setup=ENVIRONMENT.setup, egress=EgressPolicy(mode=EgressMode.OPEN)
    )
    sealed = ENVIRONMENT.model_copy(update={"registries": ()})
    assert sealed.base().egress.mode is EgressMode.NONE
    with pytest.raises(ValueError, match="registries only for a setup"):
        ProjectEnvironment(image="python:3.14-slim", registries=("pypi.org",))
    with pytest.raises(ValueError, match="each registry once"):
        ProjectEnvironment(image="python:3.14-slim", setup=("true",), registries=("a.io", "a.io"))
    for image in ("--privileged", "-v/:/host", "python 3", ""):
        with pytest.raises(ValueError):
            ProjectEnvironment(image=image)


async def test_a_kind_that_takes_its_projects_environment_pins_its_base(
    environments: Environments,
) -> None:
    """The kind that takes it pins the environment's base; a kind that does
    not keeps its own, and a project that names none changes nothing."""
    loop = environments.loop
    bare = await loop.start(TAKES.name)
    environments.projects.environment = ENVIRONMENT.base()
    takes = await loop.start(TAKES.name)
    own = await loop.start(OWN.name)

    assert await environments.pinned(takes) == ENVIRONMENT.base()
    assert await environments.pinned(own) is None, "its kind keeps its own"
    assert await environments.pinned(bare) is None, "its project named none when it was created"
    pinned = await loop.managers.workspaces.get_workspace(loop.owner, takes)
    assert pinned.egress is EgressMode.NONE, "its workspace keeps its kind's egress"


async def test_one_build_serves_the_project_and_the_next_session_runs_no_setup(
    environments: Environments,
) -> None:
    environments.projects.environment = ENVIRONMENT.base()
    first = await environments.loop.start(TAKES.name)
    second = await environments.loop.start(TAKES.name)

    assert await environments.run(first) is LoopOutcome.SUCCEEDED
    assert environments.setup.ran == list(ENVIRONMENT.setup), "the first session built it"
    assert await environments.run(second) is LoopOutcome.SUCCEEDED

    assert environments.setup.ran == list(ENVIRONMENT.setup), "the second ran no setup"
    started = environments.infra.built.started_from
    assert started[first] == started[second] == [await environments.held(ENVIRONMENT.base())]
    assert await environments.kept() == [key(ENVIRONMENT.base())]


async def test_a_changed_setup_command_builds_a_new_base_and_a_running_session_keeps_its_own(
    environments: Environments,
) -> None:
    environments.projects.environment = ENVIRONMENT.base()
    running = await environments.loop.start(TAKES.name)
    assert await environments.run(running) is LoopOutcome.SUCCEEDED

    environments.projects.environment = CHANGED.base()
    later = await environments.loop.start(TAKES.name)
    assert await environments.run(later) is LoopOutcome.SUCCEEDED
    assert await environments.run(running) is LoopOutcome.SUCCEEDED

    assert environments.setup.ran == [*ENVIRONMENT.setup, *CHANGED.setup], "built once each"
    assert await environments.pinned(running) == ENVIRONMENT.base()
    assert await environments.pinned(later) == CHANGED.base()
    started = environments.infra.built.started_from
    first = await environments.held(ENVIRONMENT.base())
    assert started[running] == [first, first], "each of its loops starts from the base it pinned"
    assert started[later] == [await environments.held(CHANGED.base())] != [first]
    assert await environments.kept() == sorted([key(ENVIRONMENT.base()), key(CHANGED.base())])


async def test_a_failed_setup_ends_the_loop_with_the_command_and_its_exit_code_and_keeps_no_base(
    environments: Environments, caplog: pytest.LogCaptureFixture
) -> None:
    environments.projects.environment = ENVIRONMENT.base()
    environments.setup.exits["pip install acme-tools"] = 1
    session_id = await environments.loop.start(TAKES.name)

    with caplog.at_level(logging.WARNING):
        assert await environments.run(session_id) is LoopOutcome.ERRORED

    told = " ".join(record.getMessage() for record in caplog.records)
    assert "the base's setup command 1, 'pip install acme-tools', exited 1" in told
    assert await environments.kept() == [], "no half-built base"
    assert environments.infra.built.started_from == {}, "no workspace started from one"


async def test_the_setup_is_given_no_secret_and_nothing_of_the_tenants_records(
    environments: Environments,
) -> None:
    """The setup's commands carry the environment's text alone, and run with
    no variable of their own: not the tenant's secret, nor the session's
    words, nor the project."""
    loop = environments.loop
    await environments.infra.get_secrets().put(loop.owner.org_id, "SERVICE_TOKEN", TOKEN)
    environments.projects.environment = ENVIRONMENT.base()
    session_id = await loop.start(TAKES.name)

    assert await environments.run(session_id) is LoopOutcome.SUCCEEDED

    assert environments.setup.ran == list(ENVIRONMENT.setup)
    assert environments.setup.envs == [{}, {}], "no variable of its own"
    for held in (TOKEN, "Check the report.", str(environments.projects.project_id)):
        assert not any(held in command for command in environments.setup.ran)
