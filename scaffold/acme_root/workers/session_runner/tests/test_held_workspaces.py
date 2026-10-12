"""The runner's sweep of the instances its host holds. A run killed mid-loop
leaves its instance prepared, its work uncommitted in it, and nothing to
release it. Once no loop item accounts for it, a pass past the grace
releases it the way a run does: its work pushed to a snapshot ref first.
An instance a live loop holds, and a directory no prepare marked, are left
alone; a push that does not land keeps the instance for the next pass,
and one the forge refuses is not tried again until the session's next
loop. An
instance whose tenant is deleted is purged, and one whose tenant or
session this database holds no record of is left alone. A session kept by
snapshots keeps an instance that no snapshot holds, until one does."""

import logging
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from contracts.step_storage import make_message
from contracts.workspaces import GitTwin, ProjectsTwin, PullRequestsTwin, ReaderTwin

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.transports import TransportInterface
from acme.infra.transports.local import DEFAULT_PATH, TransportLocalImpl
from acme.infra.workspaces import (
    Durability,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
    WorkspaceProviderInterface,
)
from acme.infra.workspaces.host import WorkspaceHostImpl
from acme.infra.workspaces.twin import WorkspaceTwinImpl
from acme.integrations.events.twin import IntegrationTwinImpl
from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, OperatorRole, RequestContext, TenantContext
from acme.om.exceptions import ValidationFailed
from acme.om.platform_agents.kinds import PROMPT_CACHE_LIFE, WARM_GRACE
from acme.om.root import Managers, ProductKinds, build_managers
from acme.om.steps.types.header import HASH_SCHEME, WorkspaceSnapshot
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tools.rules import snapshotted_step
from acme.om.work.types.work_item import WorkItem, WorkKind
from acme.om.workspaces.impl.forge import SourceControlForgeImpl
from acme.om.workspaces.rules import SNAPSHOT_PREFIX, session_branch
from acme.workers.session_runner.workspaces import Graces, HeldWorkspacesSweep

GIT = shutil.which("git")


class Connected:
    """The tenant that connected the forge twin's one installation, once the
    case names it."""

    def __init__(self) -> None:
        self.org_id: UUID | None = None

    async def __call__(self, integration: str, installation: str) -> UUID | None:
        return self.org_id


def forge(connected: Connected) -> SourceControlForgeImpl:
    """A forge that pushes to the repository on disk, which asks no credential
    of it, for the tenant `connected` names."""
    return SourceControlForgeImpl(lambda name: IntegrationTwinImpl(name, writes=True), connected)


APP = AppContext(type=AppType.WORKER, version="session-runner@test")
GRACE = WARM_GRACE
NO_PRODUCT = ProductKinds()
DIRECTORY = IsolationSpec(mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.OPEN))
TWIN = IsolationSpec(mode=IsolationMode.TWIN, egress=EgressPolicy(mode=EgressMode.NONE))
KEPT = TWIN.model_copy(update={"durability": Durability.SNAPSHOT})


def worker(isolation: IsolationSpec, name: str = "worker") -> AgentKind:
    return AgentKind(
        name=name,
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

    def __init__(
        self,
        managers: Managers,
        provider: WorkspaceProviderInterface,
        graces: Graces = NO_PRODUCT.warm_grace,
    ) -> None:
        self.managers = managers
        self.provider = provider
        self.clock = Clock()
        self.sweep = HeldWorkspacesSweep(
            provider,
            managers.tools,
            managers.workspaces,
            managers.agent_sessions,
            managers.steps,
            managers.work,
            managers.tenancy,
            graces,
            clock=self.clock,
        )
        self.owner: TenantContext

    async def start(self) -> None:
        self.owner, _ = await self.managers.tenancy.bootstrap(
            request(), "Ajax", "ajax", "ann@ajax.test", "Ann"
        )

    async def run_left(
        self, spec: IsolationSpec, kind: str = "worker"
    ) -> tuple[UUID, WorkItem, Path]:
        """What a run killed mid-loop leaves: its loop item claimed, its
        writer epoch taken, and its workspace prepared, never released."""
        managers, owner = self.managers, self.owner
        session = await managers.agent_sessions.create_session(
            owner, make_session().model_copy(update={"kind": kind, "tools": ()})
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
        return {instance.id for instance in await self.provider.held_instances()}


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
    connected = Connected()
    managers = build_managers(
        StorageMemoryImpl(),
        infra,
        agent_kinds=(worker(DIRECTORY),),
        workspace_projects=ProjectsTwin(repository=str(remote)),
        pull_requests=PullRequestsTwin(),
        source_control=forge(connected),
    )
    host = Host(managers, infra.get_workspaces())
    await host.start()
    connected.org_id = host.owner.org_id
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
    assert any(ref in notice for notice in told.notices), "the next loop is told"
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
        workspace_reader=ReaderTwin(),
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


async def test_each_instance_stays_for_its_own_kinds_grace_never_past_the_cache_life(
    tmp_path: Path,
) -> None:
    """One sweep holds each instance no run accounts for as long as its
    session's kind says: a kind that names a short grace is let go after
    it, and one that names none after the default, the prompt cache's life.
    No kind names a grace past that life: the slot refuses it."""
    brief = timedelta(minutes=1)
    with pytest.raises(ValueError, match="runs outside the prompt cache's life"):
        ProductKinds(agents=(worker(TWIN, "brief"),), graces={"brief": PROMPT_CACHE_LIFE + brief})
    kinds = ProductKinds(agents=(worker(TWIN, "brief"), worker(TWIN)), graces={"brief": brief})
    assert (kinds.warm_grace("brief"), kinds.warm_grace("worker")) == (brief, PROMPT_CACHE_LIFE)
    infra = InfraLocalImpl(tmp_path)
    managers = build_managers(
        StorageMemoryImpl(),
        infra,
        agent_kinds=kinds.agents,
        workspace_projects=ProjectsTwin(),
        pull_requests=PullRequestsTwin(),
        workspace_git=GitTwin(),
        workspace_reader=ReaderTwin(),
    )
    host = Host(managers, infra.get_workspaces(), kinds.warm_grace)
    await host.start()
    short, short_item, _ = await host.run_left(TWIN, "brief")
    default, default_item, _ = await host.run_left(TWIN)
    await managers.work.complete(host.owner, short_item)
    await managers.work.complete(host.owner, default_item)

    assert await host.passes() == 0, "both graces begin"
    assert await host.passes(brief - timedelta(seconds=1)) == 0
    assert await host.passes(timedelta(seconds=1)) == 1, "the brief kind's goes at its grace"
    assert await host.held() == {default}
    assert await host.passes(PROMPT_CACHE_LIFE - brief - timedelta(seconds=1)) == 0
    assert await host.passes(timedelta(seconds=1)) == 1, "the other's at the cache's life"
    assert await host.held() == set() and short not in await host.held()


async def test_a_push_the_forge_refuses_waits_for_the_sessions_next_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    infra = InfraLocalImpl(tmp_path)
    source = GitTwin()
    managers = build_managers(
        StorageMemoryImpl(),
        infra,
        agent_kinds=(worker(TWIN),),
        workspace_projects=ProjectsTwin(),
        pull_requests=PullRequestsTwin(),
        workspace_git=source,
        workspace_reader=ReaderTwin(),
    )
    provider = infra.get_workspaces()
    assert isinstance(provider, WorkspaceTwinImpl)
    host = Host(managers, provider)
    await host.start()
    session_id, item, _ = await host.run_left(TWIN)
    await managers.work.complete(host.owner, item)
    source.dirty = True  # the work the run left, uncommitted
    pushes: list[str] = []
    snapshot = source.snapshot

    async def refused(*args: object, **kwargs: object) -> object:
        # The forge refuses the push for good, as it does a repository no
        # installation of the tenant's holds.
        pushes.append("push")
        raise ValidationFailed("the forge refused the push")

    monkeypatch.setattr(source, "snapshot", refused)

    assert await host.passes() == 0
    assert await host.passes(GRACE) == 0, "the push was refused: nothing is let go"
    for _ in range(3):
        assert await host.passes(timedelta(seconds=30)) == 0
    assert pushes == ["push"], "the refused head is pushed once"
    assert await host.held() == {session_id}, "its instance and its work stay"

    # The session's next loop moves its head: its work is pushed again.
    await managers.steps.append_inputs(host.owner, session_id, [make_message(session_id)])
    monkeypatch.setattr(source, "snapshot", snapshot)
    assert await host.passes() == 1, "the next pass pushes it, and lets it go"
    assert await host.held() == set() and len(source.pushed) == 1


async def test_a_kept_sessions_instance_that_no_snapshot_holds_stays_until_one_does(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    infra = InfraLocalImpl(tmp_path)
    managers = build_managers(
        StorageMemoryImpl(),
        infra,
        agent_kinds=(worker(KEPT),),
        workspace_projects=ProjectsTwin(),
        pull_requests=PullRequestsTwin(),
        workspace_git=GitTwin(),
        workspace_reader=ReaderTwin(),
    )
    provider = infra.get_workspaces()
    assert isinstance(provider, WorkspaceTwinImpl)
    host = Host(managers, provider)
    await host.start()
    # A run killed before its end's snapshot: what its commands wrote outside
    # the files lives in the instance alone.
    session_id, item, _ = await host.run_left(KEPT)
    await managers.work.fail_for_good(host.owner, item, "its runner died")

    assert await host.passes() == 0, "the grace begins"
    with caplog.at_level(logging.WARNING):
        assert await host.passes(GRACE) == 0, "no snapshot holds it: it stays"
        assert await host.passes(GRACE) == 0
    assert await host.held() == {session_id}
    kept = [r for r in caplog.records if "no snapshot holds" in r.getMessage()]
    assert len(kept) == 1, "logged once for its head"

    # A snapshot taken of it as it stands: the next pass lets it go.
    epoch = (await managers.steps.get_cursor(host.owner, session_id)).epoch
    taken = WorkspaceSnapshot(
        id=new_id(), hash=HASH_SCHEME + "0" * 64, size=0, workspace_id=session_id
    )
    step = snapshotted_step(new_id(), utcnow(), session_id, new_id(), taken)
    await managers.steps.append_steps(host.owner, session_id, epoch, [step])
    assert await host.passes() == 1
    assert await host.held() == set()


async def deleted(managers: Managers, org_id: UUID) -> None:
    """The tenant's deletion carried to its end: an operator asks it, and
    the worker ends it."""
    tenancy = managers.tenancy
    await tenancy.bootstrap(
        request(), "Ops", "ops", "root@ops.test", "Root", operator_role=OperatorRole.WRITE
    )
    token = await tenancy.grant_operator_token(request(), "root@ops.test")
    admin = await tenancy.admit_operator(await tenancy.authenticate_login(request(), token.token))
    await managers.tenancy_operator.delete_org(admin, org_id)
    await tenancy.org.delete_closed_org(
        await tenancy.service_context(request(), org_id, admin.identity_id)
    )


@pytest.mark.skipif(GIT is None, reason="git is not on this host")
async def test_a_deleted_tenants_instance_is_purged_past_the_grace(
    tmp_path: Path, remote: Path
) -> None:
    infra = HostInfra(tmp_path)
    connected = Connected()
    managers = build_managers(
        StorageMemoryImpl(),
        infra,
        agent_kinds=(worker(DIRECTORY),),
        workspace_projects=ProjectsTwin(repository=str(remote)),
        pull_requests=PullRequestsTwin(),
        source_control=forge(connected),
    )
    host = Host(managers, infra.get_workspaces())
    await host.start()
    connected.org_id = host.owner.org_id
    session_id, _, here = await host.run_left(DIRECTORY)
    (here / "notes.txt").write_text("half done\n")
    await deleted(managers, host.owner.org_id)
    assert await managers.tenancy.tenant_deleted(request(), host.owner.org_id) is True

    assert await host.passes() == 0, "the grace begins"
    assert await host.held() == {session_id}
    assert await host.passes(GRACE) == 1
    assert await host.held() == set()
    assert not here.exists(), "its files go with it"
    assert git(remote, "for-each-ref", f"{SNAPSHOT_PREFIX}/") == "", "nothing is pushed"


async def test_an_instance_this_database_holds_no_record_of_is_left_alone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """After a restore to an earlier point, the host may hold instances
    whose tenant the database never had, whose session it never had, or
    whose session's history it no longer holds. Each may hold the only copy
    of its work: past the grace it stays, and is logged once."""
    infra = InfraLocalImpl(tmp_path)
    managers = build_managers(
        StorageMemoryImpl(),
        infra,
        agent_kinds=(worker(TWIN),),
        workspace_projects=ProjectsTwin(),
        pull_requests=PullRequestsTwin(),
        workspace_git=GitTwin(),
        workspace_reader=ReaderTwin(),
    )
    provider = infra.get_workspaces()
    assert isinstance(provider, WorkspaceTwinImpl)
    host = Host(managers, provider)
    await host.start()
    stranger = new_id()
    assert await managers.tenancy.tenant_deleted(request(), stranger) is None
    unknown_org = await provider.prepare(stranger, new_id(), TWIN)
    unknown_session = await provider.prepare(host.owner.org_id, new_id(), TWIN)
    session_id, item, _ = await host.run_left(TWIN)
    await managers.work.complete(host.owner, item)
    gone = await managers.steps.purge_histories([(host.owner.org_id, session_id)])
    assert gone == [(host.owner.org_id, session_id)], "its history went with its retention"

    with caplog.at_level(logging.WARNING):
        assert await host.passes() == 0
        assert await host.passes(GRACE) == 0
        assert await host.passes(GRACE) == 0
    assert await host.held() == {unknown_org.id, unknown_session.id, session_id}
    told = [record.getMessage() for record in caplog.records if "no record" in record.getMessage()]
    assert len(told) == 3, "each is logged once"
    assert any(str(stranger) in line and "its tenant" in line for line in told)
