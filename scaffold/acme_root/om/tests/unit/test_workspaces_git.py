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
        self.managers: Managers = build_managers(
            StorageMemoryImpl(),
            HostInfra(tmp_path),
            agent_kinds=(WORKER,),
            workspace_projects=ProjectsTwin(repository=str(self.remote)),
            pull_requests=self.pull_requests,
        )
        self.ctx: TenantContext = context(Role.MEMBER)

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
    assert held.branch_seen and held.notice is None


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


async def test_what_a_session_delivered_is_read_from_git_in_its_checkout(
    checkout: Checkout,
) -> None:
    session_id = await checkout.session()
    workspace = await checkout.prepare(session_id)
    here = Path(workspace.location)
    (here / "feature.txt").write_text("the feature\n")
    git(here, "add", "feature.txt")
    git(here, "-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-qm", "f")
    (here / "README.md").write_text("the project, changed\n")
    (here / "draft.txt").write_text("half done\n")

    delivered = await checkout.managers.workspaces.delivery(checkout.ctx, workspace)

    # The repository's name, as a project's evidence is keyed.
    assert delivered.project == str(checkout.remote).lower().lstrip("/").removesuffix(".git")
    assert delivered.base == checkout.main
    assert delivered.head == git(here, "rev-parse", "HEAD") != checkout.main
    assert delivered.dirty
    assert delivered.changed == ("README.md", "draft.txt", "feature.txt")


async def test_an_agent_that_moves_its_default_branch_still_delivers_the_protected_edit(
    checkout: Checkout,
) -> None:
    session_id = await checkout.session()
    workspace = await checkout.prepare(session_id)
    here = Path(workspace.location)
    (here / "checks" / "test_guard.py").write_text("def test_guard(): assert True\n")
    git(here, "-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-qam", "e")
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
    git(here, "-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-qm", "mv")

    delivered = await checkout.managers.workspaces.delivery(checkout.ctx, workspace)

    assert {"checks/test_guard.py", "checks/test_other.py"} <= set(delivered.changed)
