"""A session pinned to a host pool whose run was killed mid-loop: its
instance stays on the host that prepared it, its work uncommitted in it,
and no run lets it go. The runner's sweep and a host of the pool share one
memory storage root, as the platform's processes share one database. Once
no loop item accounts for the instance past the grace, the sweep pushes
its work to a snapshot ref through the exec relay, which the host runs, and
only then asks the host to let it go, which it does through its own
provider. A live loop's instance is kept, a push that does not land lets
nothing go, and an instance whose tenant or session the platform holds no
record of is left alone. One a person holds is theirs; the work a loop's
end kept is not pushed again; a release its host fails is asked once; and
a snapshot push the forge refuses waits for the session's next loop."""

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
from host_support import Pace, Stack, started_host
from runner_support import TOOLS, assistant

from acme.apps.host.agent import HostAgent
from acme.apps.host.ceilings import Ceilings
from acme.client.types.hosts import IsolationMode
from acme.infra.agent_workspaces import AgentWorkspace, IsolationRefused
from acme.infra.agent_workspaces import IsolationMode as ProviderMode
from acme.infra.agent_workspaces.host import AgentWorkspaceHostImpl
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import DEFAULT_PATH, TransportLocalImpl
from acme.integrations.events.twin import IntegrationTwinImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.om import platform_root
from acme.om.agent_sessions.kinds import AgentSessionWorkKind
from acme.om.agent_steps.types.header import ParkReason
from acme.om.agent_workspaces.impl.reader import RepositoryReaderGitImpl
from acme.om.agent_workspaces.rules import SNAPSHOT_PREFIX, session_branch
from acme.om.agents.loop_rules import changed_step
from acme.om.agents.types.request import Start
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, CredentialKind, RequestContext, TenantContext
from acme.om.exceptions import NotAuthorized
from acme.om.intake.types.link import Installation
from acme.om.placement.kinds import PlacementWorkKind
from acme.om.placement.types.work import WorkspaceOperation, WorkspacePayload
from acme.om.platform_agents.kinds import WARM_GRACE
from acme.om.platform_root import PlatformManagers, PlatformPorts, ProductKinds
from acme.om.work.types.work_item import WorkItem, WorkStatus
from acme.services.api.seed import seed_platform
from acme.workers.agent_session_runner.container import RunnerContainer
from acme.workers.agent_session_runner.settings import AgentSessionRunnerSettings
from acme.workers.agent_session_runner.workspaces import HeldWorkspacesSweep

from contracts.agent_workspaces import AgentProjectsTwin

GIT = shutil.which("git")
APP = AppContext(type=AppType.WORKER, version="session-runner@test")
GRACE = WARM_GRACE
KIND = assistant()
SETTINGS = AgentSessionRunnerSettings.model_validate(
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
    """The agent project's repository on disk, its default branch seeded, and the
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
    (seed / "README.md").write_text("the agent project\n")
    git(seed, "add", "README.md")
    git(seed, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "1")
    git(seed, "push", "-q", str(remote), "main")
    return remote


async def pumped[T](host: HostAgent, call: Awaitable[T]) -> T:
    """What `call` answers, while the host claims and runs what it is
    handed, as it does beside the runner."""
    running = asyncio.ensure_future(call)
    pace = Pace()
    while not running.done():
        await pace.after(await host.claim_once() is not None)
    await host.idle()
    return await running


async def claimed_loop(
    managers: PlatformManagers, owner: TenantContext, agent_session_id: UUID
) -> WorkItem:
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
            kind=AgentSessionWorkKind.LOOP,
            target_id=agent_session_id,
            idempotency_key=new_id(),
            request_id=new_id(),
            available_at=now,
        ),
    )
    claimed = await managers.work.claim(
        request(), queued.lane, [AgentSessionWorkKind.LOOP], "runner-1", timedelta(minutes=1)
    )
    assert claimed is not None and claimed[1].target_id == agent_session_id
    return claimed[1]


@dataclass
class Placed:
    """A session pinned to a host pool, its run's loop item claimed, and its
    workspace prepared on the pool's host with work in it uncommitted; the
    runner's sweep beside it on a clock the case moves."""

    managers: PlatformManagers
    owner: TenantContext
    host: HostAgent
    provider: AgentWorkspaceHostImpl
    agent_projects: AgentProjectsTwin
    remote: Path
    clock: Clock
    sweep: HeldWorkspacesSweep
    pool_id: UUID
    agent_session_id: UUID
    epoch: int
    item: WorkItem
    workspace: AgentWorkspace

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
        return {instance.id for instance in await self.provider.held_instances()}

    def refs(self) -> list[str]:
        return git(
            self.remote, "for-each-ref", "--format=%(refname)", f"{SNAPSHOT_PREFIX}/"
        ).split()

    async def notices(self) -> int:
        return len(
            (
                await self.managers.agent_workspaces.get_workspace(
                    self.owner, self.agent_session_id
                )
            ).notices
        )

    async def release(self) -> WorkItem | None:
        asked = await self.managers.work.latest_for_target(
            self.owner, PlacementWorkKind.WORKSPACE, self.agent_session_id
        )
        if asked is None:
            return None
        payload = WorkspacePayload.model_validate(asked.payload)
        return asked if payload.operation is WorkspaceOperation.RELEASE else None


async def placed(
    api: Stack, tmp_path: Path, remote: Path, grace: timedelta | None = None
) -> Placed:
    """A session of `KIND` placed on a host of a pool, its workspace there
    holding work, and the sweep over it. `grace` is the kind's warm grace;
    None takes the default."""
    assert GIT is not None
    agent_projects = AgentProjectsTwin(repository=str(remote))
    forge = IntegrationTwinImpl("forge", writes=True)
    runner = RunnerContainer.over(
        SETTINGS,
        api.container.storage,
        api.container.infra,
        IntegrationsOverImpl(
            IdentityProviderAbsentImpl(),
            scripted_model_providers(),
            {"forge": forge},
        ),
        ports=PlatformPorts(
            workspace_agent_projects=agent_projects,
            kinds=ProductKinds(
                agents=(KIND,),
                tools=lambda _managers: TOOLS,
                graces={} if grace is None else {KIND.name: grace},
            ),
        ),
    )
    managers, owner = runner.managers, api.owner
    await seed_platform(runner.storage, managers, owner, (KIND,))
    # The tenant connected the forge's installation that holds the
    # repository, so its snapshots go through it.
    await runner.storage.get_intake_storage().create_installation(
        owner.org_id,
        Installation(
            id=new_id(),
            created_at=utcnow(),
            integration="forge",
            installation=await forge.installation_of(str(remote)),
            created_by=owner.user_id,
        ),
    )
    pool = await api.pool("pool-a")
    root = tmp_path / "host" / "workspaces"
    provider = AgentWorkspaceHostImpl(root)
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
            agent_projects=None,
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
        runner.infra.get_agent_workspaces(),
        managers.tools,
        managers.agent_workspaces,
        managers.agent_sessions,
        managers.agent_steps,
        managers.work,
        managers.tenancy,
        runner.platform.kinds.warm_grace,
        clock=clock,
        exec_relay=managers.exec_relay,
    )
    # A run takes the session, its host makes the workspace, and the run's
    # tool call leaves work in it uncommitted.
    session = await managers.agents.start_agent_session(
        owner, Start(id=new_id(), kind=KIND.name, title="placed")
    )
    await api.container.managers.hosts.place_session(owner, session.id, pool.id)
    item = await claimed_loop(managers, owner, session.id)
    epoch = await managers.agent_steps.begin_run(owner, session.id)
    with pytest.raises(IsolationRefused):
        await managers.tools.prepare_agent_workspace(owner, session.id, KIND.isolation)
    assert await host.tick() is not None  # the prepare it claims
    await host.idle()
    workspace = await pumped(
        host, managers.tools.prepare_agent_workspace(owner, session.id, KIND.isolation)
    )
    assert Path(workspace.location).is_relative_to(root.resolve())
    (Path(workspace.location) / "notes.txt").write_text("half done\n")
    return Placed(
        managers=managers,
        owner=owner,
        host=host,
        provider=provider,
        agent_projects=agent_projects,
        remote=remote,
        clock=clock,
        sweep=sweep,
        pool_id=pool.id,
        agent_session_id=session.id,
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
    killed = run.agent_session_id

    # The host also holds what the platform has no record to account for:
    # an instance of a tenant it never had, and one of a session bound to
    # this host with no history.
    stranger = await provider.prepare(new_id(), new_id(), KIND.isolation)
    unrun = await managers.agents.start_agent_session(
        owner, Start(id=new_id(), kind=KIND.name, title="never ran")
    )
    await api.container.managers.hosts.place_session(owner, unrun.id, run.pool_id)
    there = await provider.prepare(owner.org_id, unrun.id, KIND.isolation)
    await managers.exec_relay.bind_workspace(
        owner, unrun.id, UUID(host.credential.claimant_id), there.location
    )

    assert await run.passes() == 0
    assert await run.passes(2 * GRACE) == 0, "the run's loop item is claimed: a live loop's"
    assert killed in await run.held()
    # Its lease ran out, and its attempts with it: the item fails for good.
    await managers.work.fail_for_good(owner, run.item, "its runner died")
    assert await run.passes() == 0, "the grace begins"
    assert await run.passes(GRACE - timedelta(seconds=1)) == 0
    run.agent_projects.repository = str(tmp_path / "gone.git")
    assert await run.passes(timedelta(seconds=1)) == 0, "a push that does not land lets nothing go"
    assert killed in await run.held()
    assert await run.release() is None
    run.agent_projects.repository = str(remote)
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
    # A person takes control, in person: the loop parks on a hand-over and
    # its item completes, and the person's commands run in the workspace
    # meanwhile.
    signed_in = run.owner.security.model_copy(
        update={"credential_kind": CredentialKind.AUTH_SESSION_TOKEN}
    )
    by_hand = run.owner.model_copy(update={"security": signed_in})
    parked = await run.managers.loop.take_over(by_hand, run.agent_session_id)
    assert parked.park is not None and parked.park.reason is ParkReason.HANDOVER
    await run.managers.work.complete(run.owner, run.item)

    assert await run.passes() == 0
    assert await run.passes(2 * GRACE) == 0, "a person holds it"
    assert await run.host.claim_once() is None
    assert run.agent_session_id in await run.held()
    assert run.refs() == [] and await run.release() is None


@pytest.mark.skipif(GIT is None, reason="git is not on this host")
async def test_after_a_loop_ends_the_sweep_lets_its_instance_go_with_no_second_snapshot(
    api: Stack, tmp_path: Path, remote: Path
) -> None:
    run = await placed(api, tmp_path, remote)
    managers, owner = run.managers, run.owner
    # The loop ends as runs end: its last step, then its own release keeps
    # the work on a snapshot and leaves the instance warm on its host.
    step = changed_step(new_id(), utcnow(), run.agent_session_id, new_id())
    await managers.agent_steps.append_agent_steps(owner, run.agent_session_id, run.epoch, [step])
    await pumped(run.host, managers.tools.release_agent_workspace(owner, run.workspace))
    await managers.work.complete(owner, run.item)
    (kept,) = run.refs()
    assert await run.notices() == 1

    assert await run.passes() == 0
    assert await run.passes(GRACE) == 1
    await run.answers()
    assert run.agent_session_id not in await run.held()
    assert run.refs() == [kept], "no second ref of the same work"
    assert await run.notices() == 1, "no second notice"


@pytest.mark.skipif(GIT is None, reason="git is not on this host")
async def test_after_a_loop_ends_its_hosted_instance_stays_warm_for_its_kinds_grace(
    api: Stack, tmp_path: Path, remote: Path
) -> None:
    """A loop's end leaves its instance warm on its host for its kind's own
    grace, read from its session's kind, and the sweep lets it go then."""
    grace = timedelta(minutes=2)
    run = await placed(api, tmp_path, remote, grace)
    managers, owner = run.managers, run.owner
    await pumped(run.host, managers.tools.release_agent_workspace(owner, run.workspace))
    await managers.work.complete(owner, run.item)

    assert await run.passes() == 0, "its grace begins"
    assert await run.passes(grace - timedelta(seconds=1)) == 0
    assert run.agent_session_id in await run.held()
    assert await run.passes(timedelta(seconds=1)) == 1, "it goes at its kind's grace"
    await run.answers()
    assert run.agent_session_id not in await run.held()


@pytest.mark.skipif(GIT is None, reason="git is not on this host")
async def test_work_after_the_last_snapshot_is_pushed_before_the_release(
    api: Stack, tmp_path: Path, remote: Path
) -> None:
    run = await placed(api, tmp_path, remote)
    managers, owner = run.managers, run.owner
    await pumped(run.host, managers.tools.release_agent_workspace(owner, run.workspace))
    await managers.work.complete(owner, run.item)
    (kept,) = run.refs()
    # The next run works in the warm instance and is killed: its step comes
    # after the snapshot, and so may its work.
    item = await claimed_loop(managers, owner, run.agent_session_id)
    epoch = await managers.agent_steps.begin_run(owner, run.agent_session_id)
    step = changed_step(new_id(), utcnow(), run.agent_session_id, new_id())
    await managers.agent_steps.append_agent_steps(owner, run.agent_session_id, epoch, [step])
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

    async def fails(workspace: AgentWorkspace) -> None:
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

    with caplog.at_level(logging.WARNING, "acme.workers.agent_session_runner.workspaces"):
        for _ in range(3):
            assert await run.passes() == 0
            assert await run.passes(GRACE) == 0, "a failed release is not asked again"
    assert await run.host.claim_once() is None
    assert await run.release() == await managers.work.get_item(owner, asked.id)
    assert len(run.refs()) == 1 and await run.notices() == 1
    failed = [r for r in caplog.records if "did not let its instance go" in r.getMessage()]
    assert len(failed) == 1, "a failed release is logged once"


@pytest.mark.skipif(GIT is None, reason="git is not on this host")
async def test_a_snapshot_push_the_forge_refuses_waits_for_the_sessions_next_loop(
    api: Stack, tmp_path: Path, remote: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await placed(api, tmp_path, remote)
    managers, owner = run.managers, run.owner
    detach = managers.agent_workspaces.detach
    pushes: list[int] = []

    async def refused(ctx: TenantContext, workspace: AgentWorkspace, epoch: int) -> None:
        # The forge refuses the push for good, as it does a repository no
        # installation of the tenant's holds.
        pushes.append(epoch)
        raise NotAuthorized("no installation of the forge this tenant connected holds it")

    monkeypatch.setattr(managers.agent_workspaces, "detach", refused)
    await managers.work.fail_for_good(owner, run.item, "its runner died")
    assert await run.passes() == 0
    assert await run.passes(GRACE) == 0, "the push was refused: nothing is let go"
    for _ in range(3):
        assert await run.passes(timedelta(seconds=30)) == 0
    assert len(pushes) == 1, "the refused head is pushed once"
    assert await run.release() is None and await run.held() == {run.agent_session_id}

    # The session's next loop moves its head: its work is pushed again.
    item = await claimed_loop(managers, owner, run.agent_session_id)
    epoch = await managers.agent_steps.begin_run(owner, run.agent_session_id)
    step = changed_step(new_id(), utcnow(), run.agent_session_id, new_id())
    await managers.agent_steps.append_agent_steps(owner, run.agent_session_id, epoch, [step])
    await managers.work.fail_for_good(owner, item, "its runner died")
    monkeypatch.setattr(managers.agent_workspaces, "detach", detach)
    assert await run.passes() == 1, "the next pass pushes it, and asks for the release"
    await run.answers()
    assert len(run.refs()) == 1 and await run.release() is not None
