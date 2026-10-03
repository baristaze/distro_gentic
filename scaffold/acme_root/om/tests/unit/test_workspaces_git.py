"""The checkout, over a directory on this host, the transport that runs its
commands here, and a repository on disk as the remote: git itself, through
the engine's one way into a workspace. A release pushes the work a loop
left to a snapshot ref and leaves the branch, the index, and the files as
they were; a branch the remote lost with no known fate fails loudly and
nothing is checked out from the default branch; one gone after its pull
request merged is cut again from it."""

import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from contracts.doubles import context
from contracts.workspaces import ProjectsTwin, PullRequestsTwin

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.keys import KeyServiceInterface
from acme.infra.transports import TransportInterface
from acme.infra.transports.local import DEFAULT_PATH, TransportLocalImpl
from acme.infra.workspaces import (
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
    Workspace,
    WorkspaceLost,
    WorkspaceProviderInterface,
)
from acme.infra.workspaces.host import WorkspaceHostImpl
from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.context import Role, TenantContext
from acme.om.root import Managers, build_managers
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.workspaces.rules import SNAPSHOT_PREFIX, session_branch
from acme.om.workspaces.types.source import PullRequestFate

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git is not on this host")

DIRECTORY = IsolationSpec(mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.OPEN))
WORKER = AgentKind(
    name="worker",
    version=1,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    tree=TreeLimits(height=1, count=0),
    isolation=DIRECTORY,
)


def git(where: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(where), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.rstrip()


class HostInfra(InfraLocalImpl):
    """The local root with a directory on this host for each workspace, and
    the transport that runs commands in it, git on its search path. The
    hosts of one deployment share its key service."""

    def __init__(self, root: Path, keys: KeyServiceInterface | None = None) -> None:
        super().__init__(root)
        self._shared_keys = keys or super().get_keys()
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

    def get_keys(self) -> KeyServiceInterface:
        return self._shared_keys


class Checkout:
    def __init__(self, tmp_path: Path) -> None:
        self.remote = tmp_path / "remote.git"
        seed = tmp_path / "seed"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
        (seed / "README.md").write_text("the project\n")
        (seed / "checks").mkdir()
        (seed / "checks" / "test_guard.py").write_text("def test_guard(): ...\n")
        git(seed, "add", "README.md", "checks")
        git(seed, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "1")
        git(seed, "push", "-q", str(self.remote), "main")
        self.main = git(self.remote, "rev-parse", "main")
        self.pull_requests = PullRequestsTwin()
        self.projects = ProjectsTwin(repository=str(self.remote))
        self.storage = StorageMemoryImpl()
        self.keys: KeyServiceInterface | None = None
        self.managers: Managers = self.host(tmp_path)
        self.ctx: TenantContext = context(Role.MEMBER)

    def host(self, root: Path) -> Managers:
        """A root on a host of its own over the one storage, as a runner on
        another host, or one that restarted, builds it."""
        infra = HostInfra(root, self.keys)
        self.keys = infra.get_keys()
        return build_managers(
            self.storage,
            infra,
            agent_kinds=(WORKER,),
            workspace_projects=self.projects,
            pull_requests=self.pull_requests,
        )

    async def session(self) -> UUID:
        made = make_session().model_copy(update={"kind": WORKER.name, "tools": ()})
        created = await self.managers.agent_sessions.create_session(self.ctx, made)
        return created.id

    async def prepare(self, session_id: UUID) -> Workspace:
        return await self.managers.tools.prepare_workspace(self.ctx, session_id, DIRECTORY)

    async def release(self, workspace: Workspace) -> None:
        await self.managers.tools.release_workspace(self.ctx, workspace)

    def push_as_a_person(self, tmp_path: Path, branch: str, name: str) -> str:
        """A person's commit on the session's branch, pushed from a clone of
        their own; answers its sha."""
        clone = tmp_path / f"clone-{name}"
        subprocess.run(
            ["git", "clone", "-q", "-b", branch, str(self.remote), str(clone)], check=True
        )
        (clone / f"{name}.txt").write_text("a person's fix\n")
        git(clone, "add", f"{name}.txt")
        git(clone, "-c", "user.name=p", "-c", "user.email=p@example.invalid", "commit", "-qm", name)
        git(clone, "push", "-q", "origin", branch)
        return git(clone, "rev-parse", "HEAD")

    def snapshots(self, branch: str) -> list[str]:
        refs = git(self.remote, "for-each-ref", "--format=%(refname)", f"{SNAPSHOT_PREFIX}/")
        return [ref for ref in refs.splitlines() if ref.startswith(f"{SNAPSHOT_PREFIX}/{branch}/")]


@pytest.fixture
def checkout(tmp_path: Path) -> Checkout:
    return Checkout(tmp_path)


# Check 2: before release, uncommitted work is committed to a snapshot ref
# and pushed.


async def test_a_release_pushes_the_uncommitted_work_beside_the_branch(checkout: Checkout) -> None:
    session_id = await checkout.session()
    branch = session_branch(session_id)
    workspace = await checkout.prepare(session_id)
    here = Path(workspace.location)
    assert git(here, "rev-parse", "--abbrev-ref", "HEAD") == branch, "cut for its first loop"
    assert git(here, "rev-parse", "HEAD") == checkout.main
    (here / "README.md").write_text("the project, changed\n")
    (here / "notes.txt").write_text("half done\n")

    await checkout.release(workspace)

    (ref,) = checkout.snapshots(branch)
    assert git(checkout.remote, "show", f"{ref}:notes.txt") == "half done"
    assert git(checkout.remote, "show", f"{ref}:README.md") == "the project, changed"
    assert git(checkout.remote, "rev-parse", f"{ref}^") == checkout.main
    assert git(checkout.remote, "branch", "--list", branch) == "", "the branch was not moved"
    status = git(here, "status", "--porcelain").splitlines()
    assert sorted(status) == [" M README.md", "?? notes.txt"], "the checkout is as it was"

    again = await checkout.prepare(session_id)
    assert again.changed is not None and ref in again.changed, "the next loop is told"
    await checkout.release(again)
    assert len(checkout.snapshots(branch)) == 2, "work still uncommitted is kept again"


async def test_a_clean_checkout_the_remote_holds_pushes_nothing(checkout: Checkout) -> None:
    session_id = await checkout.session()
    branch = session_branch(session_id)
    workspace = await checkout.prepare(session_id)
    git(Path(workspace.location), "push", "-q", "origin", branch)

    await checkout.release(workspace)

    assert checkout.snapshots(branch) == []
    held = await checkout.managers.workspaces.get_workspace(checkout.ctx, session_id)
    assert held.branch_seen and held.notices == ()


# Every instance let go is told of: a release adds its notice beside any the
# next loop has not read, and an attach clears only the notices it read.


async def a_dead_run_then_a_parked_loop(
    checkout: Checkout, tmp_path: Path
) -> tuple[UUID, Managers, Workspace, Managers, Workspace]:
    """A run on host A that left a draft in its checkout and died, then the
    run that took the session over on host B, its own draft in its checkout,
    not yet released."""
    session_id = await checkout.session()
    host_a, host_b = checkout.host(tmp_path / "a"), checkout.host(tmp_path / "b")
    await host_a.steps.begin_run(checkout.ctx, session_id)
    on_a = await host_a.tools.prepare_workspace(checkout.ctx, session_id, DIRECTORY)
    (Path(on_a.location) / "notes.txt").write_text("the dead run's draft\n")
    await host_b.steps.begin_run(checkout.ctx, session_id)
    on_b = await host_b.tools.prepare_workspace(checkout.ctx, session_id, DIRECTORY)
    (Path(on_b.location) / "notes.txt").write_text("the parked loop's draft\n")
    return session_id, host_a, on_a, host_b, on_b


async def sweep(checkout: Checkout, host: Managers, instance: Workspace) -> None:
    """The release of an instance no run accounts for, as the sweep makes
    it: a workspace named by where its host holds it, never by the run that
    prepared it."""
    workspace = Workspace(
        id=instance.id, org_id=instance.org_id, spec=instance.spec, location=instance.location
    )
    await host.tools.release_workspace(checkout.ctx, workspace)


def snapshot_of(checkout: Checkout, branch: str, notes: str) -> str:
    (ref,) = [
        ref
        for ref in checkout.snapshots(branch)
        if git(checkout.remote, "show", f"{ref}:notes.txt") == notes
    ]
    return ref


async def told_both(checkout: Checkout, host: Managers, session_id: UUID) -> None:
    """Both instances' notices wait, and the next loop is told of both, and
    then of neither again."""
    branch = session_branch(session_id)
    parked = snapshot_of(checkout, branch, "the parked loop's draft")
    dead = snapshot_of(checkout, branch, "the dead run's draft")
    held = await checkout.managers.workspaces.get_workspace(checkout.ctx, session_id)
    assert len(held.notices) == 2, "neither notice is written over"
    assert all(any(ref in told for told in held.notices) for ref in (parked, dead))
    assert all("let go at" in told for told in held.notices), "each says when it was let go"
    await host.steps.begin_run(checkout.ctx, session_id)
    following = await host.tools.prepare_workspace(checkout.ctx, session_id, DIRECTORY)
    assert following.changed is not None
    assert parked in following.changed and dead in following.changed, "told of both"
    held = await checkout.managers.workspaces.get_workspace(checkout.ctx, session_id)
    assert held.notices == (), "told once"


@pytest.mark.parametrize("swept", ["after", "before"])
async def test_a_dead_runs_instance_released_beside_a_park_is_told_with_the_parked_loops(
    checkout: Checkout, tmp_path: Path, swept: str
) -> None:
    session_id, _, on_a, host_b, on_b = await a_dead_run_then_a_parked_loop(checkout, tmp_path)
    if swept == "before":
        await sweep(checkout, checkout.host(tmp_path / "a"), on_a)
    await host_b.tools.release_workspace(checkout.ctx, on_b)  # the loop parks
    if swept == "after":
        await sweep(checkout, checkout.host(tmp_path / "a"), on_a)

    await told_both(checkout, host_b, session_id)


async def test_a_stale_run_that_attaches_after_the_next_run_began_loses_no_notice(
    checkout: Checkout, tmp_path: Path
) -> None:
    """A's run lost the session to B's before it attached, then attached;
    B parks, and A's runner, never restarted, lets A's instance go."""
    session_id = await checkout.session()
    host_a, host_b = checkout.host(tmp_path / "a"), checkout.host(tmp_path / "b")
    await host_a.steps.begin_run(checkout.ctx, session_id)
    await host_b.steps.begin_run(checkout.ctx, session_id)
    on_a = await host_a.tools.prepare_workspace(checkout.ctx, session_id, DIRECTORY)
    (Path(on_a.location) / "notes.txt").write_text("the dead run's draft\n")
    on_b = await host_b.tools.prepare_workspace(checkout.ctx, session_id, DIRECTORY)
    (Path(on_b.location) / "notes.txt").write_text("the parked loop's draft\n")

    await host_b.tools.release_workspace(checkout.ctx, on_b)  # the loop parks
    await sweep(checkout, host_a, on_a)

    await told_both(checkout, host_b, session_id)


async def test_the_newest_instance_released_by_a_runner_that_never_attached_it_is_told(
    checkout: Checkout, tmp_path: Path
) -> None:
    """Both instances wait on the sweep, and each goes in a runner that
    restarted since it attached: the newest one's work is told too."""
    session_id, _, on_a, _, on_b = await a_dead_run_then_a_parked_loop(checkout, tmp_path)

    await sweep(checkout, checkout.host(tmp_path / "a"), on_a)
    await sweep(checkout, checkout.host(tmp_path / "b"), on_b)

    await told_both(checkout, checkout.host(tmp_path / "c"), session_id)


async def test_a_notice_written_while_an_attach_syncs_outlives_that_attach(
    checkout: Checkout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A late run's release lands while the next run's attach brings its
    checkout up: that attach told only what it read, and the late run's
    notice waits for the loop after."""
    session_id = await checkout.session()
    branch = session_branch(session_id)
    host_a, host_b = checkout.host(tmp_path / "a"), checkout.host(tmp_path / "b")
    await host_a.steps.begin_run(checkout.ctx, session_id)
    on_a = await host_a.tools.prepare_workspace(checkout.ctx, session_id, DIRECTORY)
    git(Path(on_a.location), "push", "-q", "origin", branch)
    (Path(on_a.location) / "notes.txt").write_text("the late run's draft\n")
    await host_b.steps.begin_run(checkout.ctx, session_id)
    git_b = host_b.workspaces._git  # type: ignore[attr-defined]
    synced = git_b.sync

    async def sync_while_a_release_lands(*args: object, **kwargs: object) -> object:
        state = await synced(*args, **kwargs)
        await host_a.tools.release_workspace(checkout.ctx, on_a)
        return state

    monkeypatch.setattr(git_b, "sync", sync_while_a_release_lands)
    on_b = await host_b.tools.prepare_workspace(checkout.ctx, session_id, DIRECTORY)
    monkeypatch.undo()

    late = snapshot_of(checkout, branch, "the late run's draft")
    assert on_b.changed is None, "nothing was waiting when it read"
    held = await checkout.managers.workspaces.get_workspace(checkout.ctx, session_id)
    assert len(held.notices) == 1 and late in held.notices[0], "the late notice survives"
    await host_b.tools.release_workspace(checkout.ctx, on_b)
    await host_b.steps.begin_run(checkout.ctx, session_id)
    following = await host_b.tools.prepare_workspace(checkout.ctx, session_id, DIRECTORY)
    assert following.changed is not None and late in following.changed, "the next loop is told"


# Check 2: a vanished branch with no known reason fails loudly.


async def test_a_branch_the_remote_lost_fails_loudly_and_nothing_restarts_from_main(
    checkout: Checkout,
) -> None:
    session_id = await checkout.session()
    branch = session_branch(session_id)
    workspace = await checkout.prepare(session_id)
    here = Path(workspace.location)
    (here / "feature.txt").write_text("the feature\n")
    git(here, "add", "feature.txt")
    git(here, "-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-qm", "f")
    git(here, "push", "-q", "origin", branch)
    head = git(here, "rev-parse", "HEAD")
    await checkout.release(workspace)
    git(checkout.remote, "branch", "-q", "-D", branch)

    with pytest.raises(WorkspaceLost, match=branch):
        await checkout.prepare(session_id)

    assert git(here, "rev-parse", "--abbrev-ref", "HEAD") == branch
    assert git(here, "rev-parse", "HEAD") == head, "nothing was checked out from main"
    assert (here / "feature.txt").exists()

    # Its pull request merged; the checkout still holds work a release
    # could not keep.
    (here / "feature.txt").write_text("the feature, changed\n")
    (here / "notes.txt").write_text("half done\n")
    checkout.pull_requests.fates[branch] = PullRequestFate.MERGED
    rebuilt = await checkout.prepare(session_id)

    assert git(here, "rev-parse", "--abbrev-ref", "HEAD") == branch
    assert git(here, "rev-parse", "HEAD") == checkout.main, "cut again from main"
    (ref,) = checkout.snapshots(branch)
    assert git(checkout.remote, "show", f"{ref}:notes.txt") == "half done", "kept before the cut"
    assert git(checkout.remote, "show", f"{ref}:feature.txt") == "the feature, changed"
    assert rebuilt.changed is not None and "merged" in rebuilt.changed and ref in rebuilt.changed


# The branch is brought up to what its repository holds.


async def test_a_persons_push_between_loops_is_in_the_next_loops_checkout(
    checkout: Checkout, tmp_path: Path
) -> None:
    session_id = await checkout.session()
    branch = session_branch(session_id)
    workspace = await checkout.prepare(session_id)
    here = Path(workspace.location)
    git(here, "push", "-q", "origin", branch)
    await checkout.release(workspace)
    theirs = checkout.push_as_a_person(tmp_path, branch, "fix")

    again = await checkout.prepare(session_id)

    assert again.location == workspace.location, "the warm checkout"
    assert git(here, "rev-parse", "HEAD") == theirs
    assert (here / "fix.txt").read_text() == "a person's fix\n"


async def test_a_branch_that_moved_here_and_on_its_repository_fails_loudly(
    checkout: Checkout, tmp_path: Path
) -> None:
    session_id = await checkout.session()
    branch = session_branch(session_id)
    workspace = await checkout.prepare(session_id)
    here = Path(workspace.location)
    git(here, "push", "-q", "origin", branch)
    (here / "mine.txt").write_text("the agent's\n")
    git(here, "add", "mine.txt")
    git(here, "-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-qm", "m")
    mine = git(here, "rev-parse", "HEAD")
    await checkout.release(workspace)
    checkout.push_as_a_person(tmp_path, branch, "fix")

    with pytest.raises(WorkspaceLost, match=branch):
        await checkout.prepare(session_id)

    assert git(here, "rev-parse", "HEAD") == mine, "nothing was merged or reset"


# What a session delivered is read from git in its checkout.


def commit(here: Path, message: str) -> str:
    """Commits everything the checkout holds, as the agent would, and
    answers the commit."""
    git(here, "add", "-A")
    git(here, "-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-qm", message)
    return git(here, "rev-parse", "HEAD")


async def test_what_a_session_delivered_is_read_from_its_repository(checkout: Checkout) -> None:
    session_id = await checkout.session()
    branch = session_branch(session_id)
    workspace = await checkout.prepare(session_id)
    here = Path(workspace.location)
    (here / "feature.txt").write_text("the feature\n")
    pushed = commit(here, "f")
    git(here, "push", "-q", "origin", branch)
    (here / "README.md").write_text("the project, changed\n")

    delivered = await checkout.managers.workspaces.delivery(checkout.ctx, workspace)

    # The repository's name, as a project's evidence is keyed.
    assert delivered.project == str(checkout.remote).lower().lstrip("/").removesuffix(".git")
    assert (delivered.base, delivered.head) == (checkout.main, pushed)
    assert delivered.changed == ("feature.txt",), "what the repository holds, and no more"
    assert delivered.dirty, "the checkout holds work it has not delivered"

    commit(here, "not pushed")
    ahead = await checkout.managers.workspaces.delivery(checkout.ctx, workspace)
    assert ahead.head == pushed and ahead.dirty, "a commit not pushed is not delivered"


async def test_an_agent_that_moves_its_default_branch_still_delivers_the_protected_edit(
    checkout: Checkout,
) -> None:
    session_id = await checkout.session()
    workspace = await checkout.prepare(session_id)
    here = Path(workspace.location)
    (here / "checks" / "test_guard.py").write_text("def test_guard(): assert True\n")
    commit(here, "e")
    git(here, "push", "-q", "origin", session_branch(session_id))
    # The checkout's own idea of the default branch, moved past the edit.
    git(here, "update-ref", "refs/remotes/origin/main", "HEAD")

    delivered = await checkout.managers.workspaces.delivery(checkout.ctx, workspace)

    assert delivered.base == checkout.main, "the base is the repository's, not the checkout's"
    assert "checks/test_guard.py" in delivered.changed


async def test_a_moved_protected_check_is_delivered_by_the_path_it_left(
    checkout: Checkout,
) -> None:
    session_id = await checkout.session()
    workspace = await checkout.prepare(session_id)
    here = Path(workspace.location)
    git(here, "mv", "checks/test_guard.py", "checks/test_other.py")
    commit(here, "mv")
    git(here, "push", "-q", "origin", session_branch(session_id))

    delivered = await checkout.managers.workspaces.delivery(checkout.ctx, workspace)

    assert {"checks/test_guard.py", "checks/test_other.py"} <= set(delivered.changed)


async def test_a_checkout_that_redirects_its_repository_still_delivers_the_protected_edit(
    checkout: Checkout, tmp_path: Path
) -> None:
    session_id = await checkout.session()
    workspace = await checkout.prepare(session_id)
    here = Path(workspace.location)
    (here / "checks" / "test_guard.py").write_text("def test_guard(): assert True\n")
    edited = commit(here, "e")
    git(here, "push", "-q", "origin", session_branch(session_id))
    # A repository of the agent's own whose default branch is its edit, and
    # the checkout's config sending the bound repository's URL there.
    decoy = tmp_path / "decoy.git"
    git(tmp_path, "clone", "-q", "--bare", str(checkout.remote), str(decoy))
    git(here, "push", "-q", str(decoy), f"{edited}:refs/heads/main", "--force")
    git(here, "config", f"url.{decoy}.insteadOf", str(checkout.remote))

    delivered = await checkout.managers.workspaces.delivery(checkout.ctx, workspace)

    assert (delivered.base, delivered.head) == (checkout.main, edited)
    assert "checks/test_guard.py" in delivered.changed


async def test_a_replacement_the_agent_made_still_delivers_the_protected_edit(
    checkout: Checkout,
) -> None:
    session_id = await checkout.session()
    workspace = await checkout.prepare(session_id)
    here = Path(workspace.location)
    (here / "checks" / "test_guard.py").write_text("def test_guard(): assert True\n")
    edited = commit(here, "e")
    git(here, "push", "-q", "origin", session_branch(session_id))
    # The edit replaced by the default branch's commit, here and on the
    # repository both.
    git(here, "replace", edited, checkout.main)
    git(here, "push", "-q", "origin", "refs/replace/*:refs/replace/*")

    delivered = await checkout.managers.workspaces.delivery(checkout.ctx, workspace)

    assert delivered.head == edited and "checks/test_guard.py" in delivered.changed
