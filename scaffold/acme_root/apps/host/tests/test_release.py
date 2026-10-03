"""A session pinned to a host pool whose run was killed mid-loop: its
instance stays on the host that prepared it, its work uncommitted in it,
and no run lets it go. The runner's sweep and a host of the pool share one
memory storage root, as the platform's processes share one database. Once
no loop item accounts for the instance past the grace, the sweep pushes
its work to a snapshot ref through the relay, which the host runs, and
only then asks the host to let it go, which it does through its own
provider. A live loop's instance is kept, a push that does not land lets
nothing go, and an instance whose tenant or session the platform holds no
record of is left alone."""

import asyncio
import shutil
import subprocess
import sys
from collections.abc import Awaitable
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.workspaces import ProjectsTwin
from host_support import Stack, started_host
from runner_support import assistant

from acme.apps.host.agent import HostAgent
from acme.apps.host.ceilings import Ceilings
from acme.client.types import IsolationMode
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import DEFAULT_PATH, TransportLocalImpl
from acme.infra.workspaces import IsolationMode as ProviderMode
from acme.infra.workspaces import IsolationRefused
from acme.infra.workspaces.host import WorkspaceHostImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.om.agents.types.request import Start
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.placement.types.work import WorkspaceOperation, WorkspacePayload
from acme.om.root import Managers, PlatformPorts
from acme.om.work.types.work_item import WorkItem, WorkKind, WorkStatus
from acme.om.workspaces.rules import SNAPSHOT_PREFIX, session_branch
from acme.services.api.seed import seed_platform
from acme.workers.session_runner.container import RunnerContainer
from acme.workers.session_runner.settings import SessionRunnerSettings
from acme.workers.session_runner.workspaces import HeldOptions, HeldWorkspacesSweep

GIT = shutil.which("git")
APP = AppContext(type=AppType.WORKER, version="session-runner@test")
GRACE = timedelta(minutes=5)
KIND = assistant()
SETTINGS = SessionRunnerSettings.model_validate(
    {"_env_file": None, "environment": "test", "runner_id": "runner-release"}
)


class Clock:
    def __init__(self) -> None:
        self.now = utcnow()

    def __call__(self) -> datetime:
        return self.now


def request() -> RequestContext:
    return RequestContext(request_id=new_id(), app=APP)


def git(where: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(where), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.rstrip()


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """The project's repository on disk, its default branch seeded."""
    remote, seed = tmp_path / "remote.git", tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / "README.md").write_text("the project\n")
    git(seed, "add", "README.md")
    git(seed, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "1")
    git(seed, "push", "-q", str(remote), "main")
    return remote


async def pumped[T](host: HostAgent, call: Awaitable[T]) -> T:
    """What `call` answers, while the host claims and runs what it is
    handed, as it does beside the runner."""
    running = asyncio.ensure_future(call)
    while not running.done():
        if await host.claim_once() is None:
            await asyncio.sleep(0.01)
    await host.idle()
    return await running


async def claimed_loop(managers: Managers, owner: TenantContext, session_id: UUID) -> WorkItem:
    """The session's loop item, claimed by a runner, as a run holds it."""
    now = utcnow()
    queued = await managers.work.enqueue(
        owner,
        WorkItem(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=owner.user_id,
            updated_by=owner.user_id,
            kind=WorkKind.LOOP,
            target_id=session_id,
            idempotency_key=new_id(),
            request_id=new_id(),
            available_at=now,
        ),
    )
    claimed = await managers.work.claim(
        request(), queued.lane, [WorkKind.LOOP], "runner-1", timedelta(minutes=1)
    )
    assert claimed is not None and claimed[1].target_id == session_id
    return claimed[1]


@pytest.mark.skipif(GIT is None, reason="git is not on this host")
async def test_a_killed_runs_instance_on_its_host_is_released_past_the_grace_with_its_work_kept(
    api: Stack, tmp_path: Path, remote: Path
) -> None:
    assert GIT is not None
    projects = ProjectsTwin(repository=str(remote))
    runner = RunnerContainer.over(
        SETTINGS,
        api.container.storage,
        api.container.infra,
        IntegrationsOverImpl(IdentityProviderAbsentImpl(), scripted_model_providers()),
        agent_kinds=(KIND,),
        ports=PlatformPorts(workspace_projects=projects),
    )
    managers, owner = runner.managers, api.owner
    await seed_platform(runner.storage, managers, owner, (KIND,))
    pool = await api.pool("pool-a")
    root = tmp_path / "host" / "workspaces"
    provider = WorkspaceHostImpl(root)
    found = f"{Path(GIT).parent}:{Path(sys.executable).parent}"
    transport = TransportLocalImpl(
        tmp_path / "host" / "records",
        SecretsLocalImpl(None),
        BrokerNullImpl(),
        search_path=f"{found}:{DEFAULT_PATH}",
    )
    host = await started_host(
        api,
        pool.id,
        api.settings(tmp_path / "host" / "home", None),
        Ceilings(
            projects=None,
            min_isolation=IsolationMode.directory,
            egress=None,
            readable=(str(root),),
        ),
        IsolationMode.directory,
        {ProviderMode.HOST: transport},
        {ProviderMode.HOST: provider},
    )
    clock = Clock()
    sweep = HeldWorkspacesSweep(
        runner.infra.get_workspaces(),
        managers.tools,
        managers.workspaces,
        managers.agent_sessions,
        managers.steps,
        managers.work,
        managers.tenancy,
        HeldOptions(grace=GRACE),
        clock=clock,
        relay=managers.relay,
    )

    async def passes(after: timedelta = timedelta(0)) -> int:
        clock.now += after
        return await pumped(host, sweep(request()))

    async def held() -> set[UUID]:
        return {instance.id for instance in await provider.held()}

    # A run takes the session, its host makes the workspace, and the run's
    # tool call leaves work in it uncommitted.
    killed = await managers.agents.start_session(
        owner, Start(id=new_id(), kind=KIND.name, title="killed")
    )
    await api.container.managers.hosts.place_session(owner, killed.id, pool.id)
    item = await claimed_loop(managers, owner, killed.id)
    await managers.steps.begin_run(owner, killed.id)
    with pytest.raises(IsolationRefused):
        await managers.tools.prepare_workspace(owner, killed.id, KIND.isolation)
    assert await host.tick() is not None  # the prepare it claims
    await host.idle()
    workspace = await pumped(
        host, managers.tools.prepare_workspace(owner, killed.id, KIND.isolation)
    )
    here = Path(workspace.location)
    assert here.is_relative_to(root.resolve())
    (here / "notes.txt").write_text("half done\n")

    # The host also holds what the platform has no record to account for:
    # an instance of a tenant it never had, and one of a session bound to
    # this host with no history.
    stranger = await provider.prepare(new_id(), new_id(), KIND.isolation)
    unrun = await managers.agents.start_session(
        owner, Start(id=new_id(), kind=KIND.name, title="never ran")
    )
    await api.container.managers.hosts.place_session(owner, unrun.id, pool.id)
    there = await provider.prepare(owner.org_id, unrun.id, KIND.isolation)
    await managers.relay.bind_workspace(
        owner, unrun.id, UUID(host.credential.host_id), there.location
    )

    assert await passes() == 0
    assert await passes(2 * GRACE) == 0, "the run's loop item is claimed: a live loop's"
    assert killed.id in await held()
    # Its lease ran out, and its attempts with it: the item fails for good.
    await managers.work.fail_for_good(owner, item, "its runner died")
    assert await passes() == 0, "the grace begins"
    assert await passes(GRACE - timedelta(seconds=1)) == 0
    projects.repository = str(tmp_path / "gone.git")
    assert await passes(timedelta(seconds=1)) == 0, "a push that does not land lets nothing go"
    assert killed.id in await held()
    projects.repository = str(remote)
    assert await passes() == 1
    assert await host.claim_once() is not None  # the release, on this host's lane
    await host.idle()

    assert await held() == {stranger.id, unrun.id}, "only the killed run's instance goes"
    (ref,) = git(remote, "for-each-ref", "--format=%(refname)", f"{SNAPSHOT_PREFIX}/").split()
    assert ref.startswith(f"{SNAPSHOT_PREFIX}/{session_branch(killed.id)}/")
    assert git(remote, "show", f"{ref}:notes.txt") == "half done", "its work is on the snapshot"
    assert (here / "notes.txt").read_text() == "half done\n", "a release keeps the files"
    release = await managers.work.latest_for_target(owner, WorkKind.WORKSPACE, killed.id)
    assert release is not None and release.status is WorkStatus.DONE
    assert WorkspacePayload.model_validate(release.payload).operation is WorkspaceOperation.RELEASE

    # Released since its last loop: no pass asks again, and nothing starts it.
    assert await passes(GRACE) == 0
    assert await host.claim_once() is None
    assert await held() == {stranger.id, unrun.id}
