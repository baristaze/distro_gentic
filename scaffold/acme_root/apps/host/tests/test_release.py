"""A session pinned to a host pool whose run was killed mid-loop: its
instance stays on the host that prepared it, its work uncommitted in it,
and no run lets it go. The runner's sweep and a host of the pool share one
memory storage root, as the platform's processes share one database. Once
no loop item accounts for the instance past the grace, the sweep pushes
its work to a snapshot ref through the relay, which the host runs, and
only then asks the host to let it go, which it does through its own
provider. A live loop's instance is kept, a push that does not land lets
nothing go, and an instance whose tenant or session the platform holds no
record of is left alone. One a person holds is theirs; the work a loop's
end kept is not pushed again; and a release its host fails is asked once."""

import asyncio
import logging
import shutil
import subprocess
import sys
from collections.abc import Awaitable
from dataclasses import dataclass
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
from acme.infra.workspaces import IsolationRefused, Workspace
from acme.infra.workspaces.host import WorkspaceHostImpl
from acme.integrations.events.twin import IntegrationTwinImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.om import root as platform_root
from acme.om.agents.loop_rules import changed_step
from acme.om.agents.types.request import Start
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.placement.types.work import WorkspaceOperation, WorkspacePayload
from acme.om.root import Managers, PlatformPorts, ProductKinds
from acme.om.steps.types.header import ParkReason
from acme.om.work.types.work_item import WorkItem, WorkKind, WorkStatus
from acme.om.workspaces.impl.reader import RepositoryReaderGitImpl
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
def remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The project's repository on disk, its default branch seeded, and the
    reader the runner's root builds allowed to read a path, as a deployed
    one is not."""
    monkeypatch.setattr(
        platform_root,
        "RepositoryReaderGitImpl",
        lambda **options: RepositoryReaderGitImpl(**{**options, "on_disk": True}),
    )
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


@dataclass
class Placed:
    """A session pinned to a host pool, its run's loop item claimed, and its
    workspace prepared on the pool's host with work in it uncommitted; the
    runner's sweep beside it on a clock the case moves."""

    managers: Managers
    owner: TenantContext
    host: HostAgent
    provider: WorkspaceHostImpl
    projects: ProjectsTwin
    remote: Path
    clock: Clock
    sweep: HeldWorkspacesSweep
    pool_id: UUID
    session_id: UUID
    epoch: int
    item: WorkItem
    workspace: Workspace

    @property
    def here(self) -> Path:
        return Path(self.workspace.location)

    async def passes(self, after: timedelta = timedelta(0)) -> int:
        """One pass of the sweep, `after` later, while the host runs what the
        pass sends it."""
        self.clock.now += after
        return await pumped(self.host, self.sweep(request()))

    async def answers(self) -> None:
        """The host runs what its lane still holds."""
        while await self.host.claim_once() is not None:
            pass
        await self.host.idle()

    async def held(self) -> set[UUID]:
        return {instance.id for instance in await self.provider.held()}

    def refs(self) -> list[str]:
        return git(
            self.remote, "for-each-ref", "--format=%(refname)", f"{SNAPSHOT_PREFIX}/"
        ).split()

    async def notices(self) -> int:
        return len(
            (await self.managers.workspaces.get_workspace(self.owner, self.session_id)).notices
        )

    async def release(self) -> WorkItem | None:
        asked = await self.managers.work.latest_for_target(
            self.owner, WorkKind.WORKSPACE, self.session_id
        )
        if asked is None:
            return None
        payload = WorkspacePayload.model_validate(asked.payload)
        return asked if payload.operation is WorkspaceOperation.RELEASE else None


async def placed(api: Stack, tmp_path: Path, remote: Path) -> Placed:
    assert GIT is not None
    projects = ProjectsTwin(repository=str(remote))
    runner = RunnerContainer.over(
        SETTINGS,
        api.container.storage,
        api.container.infra,
        IntegrationsOverImpl(
            IdentityProviderAbsentImpl(),
            scripted_model_providers(),
            {"forge": IntegrationTwinImpl("forge", writes=True)},
        ),
        ports=PlatformPorts(workspace_projects=projects, kinds=ProductKinds(agents=(KIND,))),
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
    # A run takes the session, its host makes the workspace, and the run's
    # tool call leaves work in it uncommitted.
    session = await managers.agents.start_session(
        owner, Start(id=new_id(), kind=KIND.name, title="placed")
    )
    await api.container.managers.hosts.place_session(owner, session.id, pool.id)
    item = await claimed_loop(managers, owner, session.id)
    epoch = await managers.steps.begin_run(owner, session.id)
    with pytest.raises(IsolationRefused):
        await managers.tools.prepare_workspace(owner, session.id, KIND.isolation)
    assert await host.tick() is not None  # the prepare it claims
    await host.idle()
    workspace = await pumped(
        host, managers.tools.prepare_workspace(owner, session.id, KIND.isolation)
    )
    assert Path(workspace.location).is_relative_to(root.resolve())
    (Path(workspace.location) / "notes.txt").write_text("half done\n")
    return Placed(
        managers=managers,
        owner=owner,
        host=host,
        provider=provider,
        projects=projects,
        remote=remote,
        clock=clock,
        sweep=sweep,
        pool_id=pool.id,
        session_id=session.id,
        epoch=epoch,
        item=item,
        workspace=workspace,
    )


@pytest.mark.skipif(GIT is None, reason="git is not on this host")
async def test_a_killed_runs_instance_on_its_host_is_released_past_the_grace_with_its_work_kept(
    api: Stack, tmp_path: Path, remote: Path
) -> None:
    run = await placed(api, tmp_path, remote)
    managers, owner, provider, host = run.managers, run.owner, run.provider, run.host
    killed = run.session_id

    # The host also holds what the platform has no record to account for:
    # an instance of a tenant it never had, and one of a session bound to
    # this host with no history.
    stranger = await provider.prepare(new_id(), new_id(), KIND.isolation)
    unrun = await managers.agents.start_session(
        owner, Start(id=new_id(), kind=KIND.name, title="never ran")
    )
    await api.container.managers.hosts.place_session(owner, unrun.id, run.pool_id)
    there = await provider.prepare(owner.org_id, unrun.id, KIND.isolation)
    await managers.relay.bind_workspace(
        owner, unrun.id, UUID(host.credential.host_id), there.location
    )

    assert await run.passes() == 0
    assert await run.passes(2 * GRACE) == 0, "the run's loop item is claimed: a live loop's"
    assert killed in await run.held()
    # Its lease ran out, and its attempts with it: the item fails for good.
    await managers.work.fail_for_good(owner, run.item, "its runner died")
    assert await run.passes() == 0, "the grace begins"
    assert await run.passes(GRACE - timedelta(seconds=1)) == 0
    run.projects.repository = str(tmp_path / "gone.git")
    assert await run.passes(timedelta(seconds=1)) == 0, "a push that does not land lets nothing go"
    assert killed in await run.held()
    assert await run.release() is None
    run.projects.repository = str(remote)
    assert await run.passes() == 1
    await run.answers()  # the release, on this host's lane

    assert await run.held() == {stranger.id, unrun.id}, "only the killed run's instance goes"
    (ref,) = run.refs()
    assert ref.startswith(f"{SNAPSHOT_PREFIX}/{session_branch(killed)}/")
    assert git(remote, "show", f"{ref}:notes.txt") == "half done", "its work is on the snapshot"
    assert (run.here / "notes.txt").read_text() == "half done\n", "a release keeps the files"
    release = await run.release()
    assert release is not None and release.status is WorkStatus.DONE

    # Released since its last loop: no pass asks again, and nothing starts it.
    assert await run.passes(GRACE) == 0
    assert await host.claim_once() is None
    assert await run.held() == {stranger.id, unrun.id}


@pytest.mark.skipif(GIT is None, reason="git is not on this host")
async def test_a_session_parked_on_a_hand_over_keeps_its_hosted_instance_past_the_grace(
    api: Stack, tmp_path: Path, remote: Path
) -> None:
    run = await placed(api, tmp_path, remote)
    # A person takes control: the loop parks on a hand-over and its item
    # completes, and the person's commands run in the workspace meanwhile.
    parked = await run.managers.loop.take_over(run.owner, run.session_id)
    assert parked.park is not None and parked.park.reason is ParkReason.HANDOVER
    await run.managers.work.complete(run.owner, run.item)

    assert await run.passes() == 0
    assert await run.passes(2 * GRACE) == 0, "a person holds it"
    assert await run.host.claim_once() is None
    assert run.session_id in await run.held()
    assert run.refs() == [] and await run.release() is None


@pytest.mark.skipif(GIT is None, reason="git is not on this host")
async def test_after_a_loop_ends_the_sweep_lets_its_instance_go_with_no_second_snapshot(
    api: Stack, tmp_path: Path, remote: Path
) -> None:
    run = await placed(api, tmp_path, remote)
    managers, owner = run.managers, run.owner
    # The loop ends as runs end: its last step, then its own release keeps
    # the work on a snapshot and leaves the instance warm on its host.
    step = changed_step(new_id(), utcnow(), run.session_id, new_id())
    await managers.steps.append_steps(owner, run.session_id, run.epoch, [step])
    await pumped(run.host, managers.tools.release_workspace(owner, run.workspace))
    await managers.work.complete(owner, run.item)
    (kept,) = run.refs()
    assert await run.notices() == 1

    assert await run.passes() == 0
    assert await run.passes(GRACE) == 1
    await run.answers()
    assert run.session_id not in await run.held()
    assert run.refs() == [kept], "no second ref of the same work"
    assert await run.notices() == 1, "no second notice"


@pytest.mark.skipif(GIT is None, reason="git is not on this host")
async def test_work_after_the_last_snapshot_is_pushed_before_the_release(
    api: Stack, tmp_path: Path, remote: Path
) -> None:
    run = await placed(api, tmp_path, remote)
    managers, owner = run.managers, run.owner
    await pumped(run.host, managers.tools.release_workspace(owner, run.workspace))
    await managers.work.complete(owner, run.item)
    (kept,) = run.refs()
    # The next run works in the warm instance and is killed: its step comes
    # after the snapshot, and so may its work.
    item = await claimed_loop(managers, owner, run.session_id)
    epoch = await managers.steps.begin_run(owner, run.session_id)
    step = changed_step(new_id(), utcnow(), run.session_id, new_id())
    await managers.steps.append_steps(owner, run.session_id, epoch, [step])
    (run.here / "more.txt").write_text("more\n")
    await managers.work.fail_for_good(owner, item, "its runner died")

    assert await run.passes() == 0
    assert await run.passes(GRACE) == 1
    await run.answers()
    (pushed,) = set(run.refs()) - {kept}
    assert git(remote, "show", f"{pushed}:more.txt") == "more"


@pytest.mark.skipif(GIT is None, reason="git is not on this host")
async def test_a_release_its_host_fails_is_asked_once(
    api: Stack,
    tmp_path: Path,
    remote: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await placed(api, tmp_path, remote)
    managers, owner = run.managers, run.owner

    async def fails(workspace: Workspace) -> None:
        raise RuntimeError("the instance does not go")

    # Its host's provider fails every release, so the host never answers
    # one: its leases run out, and it fails for good.
    monkeypatch.setattr(run.provider, "release", fails)
    await managers.work.fail_for_good(owner, run.item, "its runner died")
    assert await run.passes() == 0
    assert await run.passes(GRACE) == 1
    await run.answers()
    asked = await run.release()
    assert asked is not None and asked.status is WorkStatus.CLAIMED
    await managers.work.fail_for_good(owner, asked, "its lease ran out")

    with caplog.at_level(logging.WARNING, "acme.workers.session_runner.workspaces"):
        for _ in range(3):
            assert await run.passes() == 0
            assert await run.passes(GRACE) == 0, "a failed release is not asked again"
    assert await run.host.claim_once() is None
    assert await run.release() == await managers.work.get_item(owner, asked.id)
    assert len(run.refs()) == 1 and await run.notices() == 1
    failed = [r for r in caplog.records if "did not let its instance go" in r.getMessage()]
    assert len(failed) == 1, "a failed release is logged once"
