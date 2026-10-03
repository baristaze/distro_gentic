"""The runner's sweep of the instances its host holds. A run killed mid-loop
leaves its instance prepared, its work uncommitted in it, and nothing to
release it. Once no loop item accounts for it, a pass past the grace
releases it the way a run does: its work pushed to a snapshot ref first.
An instance a live loop holds, and a directory no prepare marked, are left
alone; a push that does not land keeps the instance for the next pass; and
an instance whose session is gone is purged."""

import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from contracts.workspaces import GitTwin, ProjectsTwin, PullRequestsTwin

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.transports import TransportInterface
from acme.infra.transports.local import DEFAULT_PATH, TransportLocalImpl
from acme.infra.workspaces import (
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
    WorkspaceProviderInterface,
)
from acme.infra.workspaces.host import WorkspaceHostImpl
from acme.infra.workspaces.twin import WorkspaceTwinImpl
from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.root import Managers, build_managers
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.work.types.work_item import WorkItem, WorkKind
from acme.om.workspaces.rules import SNAPSHOT_PREFIX, session_branch
from acme.workers.session_runner.workspaces import HeldOptions, HeldWorkspacesSweep

GIT = shutil.which("git")
APP = AppContext(type=AppType.WORKER, version="session-runner@test")
GRACE = timedelta(minutes=5)
DIRECTORY = IsolationSpec(mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.OPEN))
TWIN = IsolationSpec(mode=IsolationMode.TWIN, egress=EgressPolicy(mode=EgressMode.NONE))


def worker(isolation: IsolationSpec) -> AgentKind:
    return AgentKind(
        name="worker",
        version=1,
        done_rule=DoneRule.ANSWER,
        authority=AuthorityMode.DELEGATED,
        tree=TreeLimits(height=1, count=0),
        isolation=isolation,
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


class HostInfra(InfraLocalImpl):
    """The local root with a directory on this host for each workspace, and
    the transport that runs commands in it, git on its search path."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        assert GIT is not None
        found = f"{Path(GIT).parent}:{Path(sys.executable).parent}"
        self._host = WorkspaceHostImpl(root / "workspaces")
        self._local = TransportLocalImpl(
            root / "records",
            self.get_secrets(),
            self.get_broker(),
            search_path=f"{found}:{DEFAULT_PATH}",
        )

    def get_workspaces(self) -> WorkspaceProviderInterface:
        return self._host

    def get_transport(self) -> TransportInterface:
        return self._local


class Host:
    """One runner's host over memory: a tenant, its sessions, and the sweep
    on a clock the case moves."""

    def __init__(self, managers: Managers, provider: WorkspaceProviderInterface) -> None:
        self.managers = managers
        self.provider = provider
        self.clock = Clock()
        self.sweep = HeldWorkspacesSweep(
            provider,
            managers.tools,
            managers.workspaces,
            managers.steps,
            managers.work,
            managers.tenancy,
            HeldOptions(grace=GRACE),
            clock=self.clock,
        )
        self.owner: TenantContext

    async def start(self) -> None:
        self.owner, _ = await self.managers.tenancy.bootstrap(
            request(), "Ajax", "ajax", "ann@ajax.test", "Ann"
        )

    async def run_left(self, spec: IsolationSpec) -> tuple[UUID, WorkItem, Path]:
        """What a run killed mid-loop leaves: its loop item claimed, its
        writer epoch taken, and its workspace prepared, never released."""
        managers, owner = self.managers, self.owner
        session = await managers.agent_sessions.create_session(
            owner, make_session().model_copy(update={"kind": "worker", "tools": ()})
        )
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
                target_id=session.id,
                idempotency_key=new_id(),
                request_id=new_id(),
                available_at=now,
            ),
        )
        claimed = await managers.work.claim(
            request(), queued.lane, [WorkKind.LOOP], "runner-1", timedelta(minutes=1)
        )
        assert claimed is not None and claimed[1].target_id == session.id
        await managers.steps.begin_run(owner, session.id)
        workspace = await managers.tools.prepare_workspace(owner, session.id, spec)
        return session.id, claimed[1], Path(workspace.location)

    async def passes(self, after: timedelta = timedelta(0)) -> int:
        self.clock.now += after
        return await self.sweep(request())

    async def held(self) -> set[UUID]:
        return {instance.id for instance in await self.provider.held()}


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


@pytest.mark.skipif(GIT is None, reason="git is not on this host")
async def test_a_killed_runs_instance_is_released_past_the_grace_with_its_work_on_a_snapshot(
    tmp_path: Path, remote: Path
) -> None:
    infra = HostInfra(tmp_path)
    managers = build_managers(
        StorageMemoryImpl(),
        infra,
        agent_kinds=(worker(DIRECTORY),),
        workspace_projects=ProjectsTwin(repository=str(remote)),
        pull_requests=PullRequestsTwin(),
    )
    host = Host(managers, infra.get_workspaces())
    await host.start()
    killed, item, here = await host.run_left(DIRECTORY)
    (here / "notes.txt").write_text("half done\n")
    live, _, _ = await host.run_left(DIRECTORY)
    stray = tmp_path / "workspaces" / host.owner.org_id.hex / new_id().hex
    stray.mkdir()

    assert await host.passes() == 0, "the killed run's item is still claimed"
    # Its lease ran out, and its attempts with it: the item fails for good.
    await managers.work.fail_for_good(host.owner, item, "its runner died")
    assert await host.passes() == 0, "the grace begins"
    assert await host.passes(GRACE - timedelta(seconds=1)) == 0
    assert await host.passes(timedelta(seconds=1)) == 1

    (ref,) = git(remote, "for-each-ref", "--format=%(refname)", f"{SNAPSHOT_PREFIX}/").split()
    assert ref.startswith(f"{SNAPSHOT_PREFIX}/{session_branch(killed)}/")
    assert git(remote, "show", f"{ref}:notes.txt") == "half done", "its work is on the snapshot"
    told = await managers.workspaces.get_workspace(host.owner, killed)
    assert told.notice is not None and ref in told.notice, "the next loop is told"
    assert await host.held() == {live}, "the live loop's instance is left alone"
    assert (here / "notes.txt").read_text() == "half done\n", "a release keeps the files"
    assert stray.is_dir(), "a directory no prepare marked is left alone"
    assert await host.passes(GRACE) == 0
    assert await host.held() == {live}


async def test_a_push_that_does_not_land_keeps_the_instance_for_the_next_pass(
    tmp_path: Path,
) -> None:
    infra = InfraLocalImpl(tmp_path)
    source = GitTwin(refuses_push=True)
    managers = build_managers(
        StorageMemoryImpl(),
        infra,
        agent_kinds=(worker(TWIN),),
        workspace_projects=ProjectsTwin(),
        pull_requests=PullRequestsTwin(),
        workspace_git=source,
    )
    provider = infra.get_workspaces()
    assert isinstance(provider, WorkspaceTwinImpl)
    host = Host(managers, provider)
    await host.start()
    session_id, item, _ = await host.run_left(TWIN)
    await managers.work.complete(host.owner, item)
    source.dirty = True  # the work the run left, uncommitted

    assert await host.passes() == 0
    assert await host.passes(GRACE) == 0, "the push failed: nothing is let go"
    assert await host.held() == {session_id}
    source.refuses_push = False
    assert await host.passes() == 1, "the next pass pushes it, and lets it go"
    assert await host.held() == set() and len(source.pushed) == 1


async def test_an_instance_whose_session_is_gone_is_purged(tmp_path: Path) -> None:
    infra = InfraLocalImpl(tmp_path)
    managers = build_managers(
        StorageMemoryImpl(),
        infra,
        agent_kinds=(worker(TWIN),),
        workspace_projects=ProjectsTwin(),
        pull_requests=PullRequestsTwin(),
        workspace_git=GitTwin(),
    )
    provider = infra.get_workspaces()
    assert isinstance(provider, WorkspaceTwinImpl)
    host = Host(managers, provider)
    await host.start()
    session_id, item, _ = await host.run_left(TWIN)
    await managers.work.complete(host.owner, item)
    gone = await managers.steps.purge_histories([(host.owner.org_id, session_id)])
    assert gone == [(host.owner.org_id, session_id)], "its history went with its retention"

    assert await host.passes() == 0
    assert await host.passes(GRACE) == 1
    assert await host.held() == set()
