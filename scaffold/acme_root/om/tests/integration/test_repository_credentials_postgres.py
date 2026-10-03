"""A private repository's work, over Postgres as a process wires it: the
repository is served by git's own HTTP backend behind basic authentication,
the project's fetch credential is given to the platform and kept in the
tenant's store, and the platform's own git alone is handed it. The forge
writes with a credential of its own. The session's workspace, a directory
on this host, checks the repository out and delivers to it, and holds
neither."""

import base64
import shutil
import subprocess
import sys
import threading
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

import pytest
from contracts.platform_agents import CORPUS
from contracts.workspaces import GitTwin, ProjectsTwin
from pydantic import SecretStr

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
from acme.integrations.events.twin import IntegrationTwinImpl
from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.agents.types.request import Start
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext
from acme.om.exceptions import Unavailable
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.platform_agents.kinds import ENGINEER_KIND
from acme.om.root import Managers, build_managers
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings
from acme.om.workspaces import rules
from acme.om.workspaces.impl.forge import SourceControlForgeImpl
from acme.om.workspaces.impl.reader import RepositoryReaderGitImpl
from acme.om.workspaces.types.credential import FetchCredential

GIT = shutil.which("git")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(GIT is None, reason="git is not on this host"),
]

APP = AppContext(type=AppType.PORTAL, version="portal@test")
DIRECTORY = IsolationSpec(mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.OPEN))
WORKER = AgentKind(
    name="worker",
    version=1,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    tree=TreeLimits(height=1, count=0),
    isolation=DIRECTORY,
)
ENGINEER = ENGINEER_KIND.model_copy(
    update={"version": ENGINEER_KIND.version + 1, "isolation": DIRECTORY}
)
"""The shipped engineer, in a directory on this host."""
USER, PASSWORD = "reader", "fetch-only-5f1c0e9a7d"
WRITER, WRITER_PASSWORD = "forge", "forge-writes-2c7d91e4b8"


def git(where: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(where), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def grep(where: Path, *patterns: str) -> subprocess.CompletedProcess[str]:
    """Every file under `where` that holds any of `patterns`."""
    found = [arg for pattern in patterns for arg in ("-e", pattern)]
    return subprocess.run(
        ["grep", "-r", "-l", *found, str(where)], capture_output=True, text=True, check=False
    )


def fetches(where: Path) -> bool:
    """Whether the checkout at `where` fetches its `origin` with what it
    holds, and nothing of this host's git configuration."""
    done = subprocess.run(
        ["git", "-C", str(where), "fetch", "-q", "origin"],
        env={
            "PATH": str(Path(GIT or "git").parent),
            "HOME": str(where),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
        capture_output=True,
        check=False,
    )
    return done.returncode == 0


class PrivateGit(ThreadingHTTPServer):
    """Git's HTTP backend over the repositories under `root`, answering a read
    that carries `USER` and `PASSWORD`, and a read or a push that carries
    the forge's `WRITER` and `WRITER_PASSWORD`; it counts the requests that
    carried either."""

    def __init__(self, root: Path) -> None:
        super().__init__(("127.0.0.1", 0), PrivateGitHandler)
        self.root = root
        self.expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
        self.writer = "Basic " + base64.b64encode(f"{WRITER}:{WRITER_PASSWORD}".encode()).decode()
        self.authorized = 0
        self.refused = 0

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host!s}:{port}/ajax/app.git"


class PrivateGitHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._serve()

    def do_POST(self) -> None:
        self._serve()

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _serve(self) -> None:
        served = cast(PrivateGit, self.server)
        given = self.headers.get("Authorization")
        pushes = "git-receive-pack" in self.path
        if given != served.writer and (given != served.expected or pushes):
            served.refused += 1
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="git"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        served.authorized += 1
        path, _, query = self.path.partition("?")
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        env = {
            "PATH": str(Path(GIT or "git").parent),
            "GIT_PROJECT_ROOT": str(served.root),
            "GIT_HTTP_EXPORT_ALL": "1",
            "REQUEST_METHOD": self.command,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": str(len(body)),
            "HTTP_CONTENT_ENCODING": self.headers.get("Content-Encoding", ""),
            "GIT_PROTOCOL": self.headers.get("Git-Protocol", ""),
            "REMOTE_USER": USER,
            "REMOTE_ADDR": "127.0.0.1",
        }
        done = subprocess.run(
            [GIT or "git", "http-backend"], input=body, env=env, capture_output=True, check=False
        )
        head, _, payload = done.stdout.partition(b"\r\n\r\n")
        status = 200
        headers: list[tuple[str, str]] = []
        for line in head.decode().splitlines():
            name, _, value = line.partition(":")
            if name.lower() == "status":
                status = int(value.split()[0])
            elif name:
                headers.append((name, value.strip()))
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def private_git(tmp_path: Path) -> Iterator[PrivateGit]:
    server = PrivateGit(tmp_path / "served")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


class HostInfra(InfraLocalImpl):
    """The local root with a directory on this host for each workspace, and
    the transport that runs commands in it."""

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


@pytest.fixture
async def storage(
    migration_settings: MigrationSettings, migrated: object
) -> AsyncIterator[StoragePostgresImpl]:
    root = StoragePostgresImpl(
        migration_settings.role_urls(),
        migration_settings.role_pools(),
        system_urls=migration_settings.system_role_urls(),
    )
    yield root
    await root.close()


def on_loopback() -> RepositoryReaderGitImpl:
    """The platform's reader of a repository this host serves on its
    loopback, which a deployment's reader never reads from."""
    return RepositoryReaderGitImpl(walled=())


def a_delivery(served: Path) -> tuple[str, str]:
    """The private repository: its default branch, and a session's branch
    one change ahead of it, pushed as the session would. Answers the two
    commits."""
    remote = served / "ajax" / "app.git"
    seed = served.parent / "seed"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / "README.md").write_text("the project\n")
    git(seed, "add", "README.md")
    git(seed, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "1")
    git(seed, "push", "-q", str(remote), "main")
    return git(seed, "rev-parse", "HEAD"), str(remote)


async def test_a_private_repositorys_delivery_is_read_with_the_fetch_credential_alone(
    tmp_path: Path, storage: StoragePostgresImpl, private_git: PrivateGit
) -> None:
    main, remote = a_delivery(private_git.root)
    projects = ProjectsTwin(repository=private_git.url)
    infra = HostInfra(tmp_path / "host")
    managers: Managers = build_managers(
        storage,
        infra,
        agent_kinds=(WORKER,),
        workspace_projects=projects,
        workspace_git=GitTwin(),
        workspace_reader=on_loopback(),
    )
    owner, _ = await managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP),
        "Ajax",
        f"ajax-{new_id().hex[-8:]}",
        f"ann-{new_id().hex[-8:]}@example.test",
        "Ann",
    )
    session = await managers.agents.start_session(
        owner, Start(id=new_id(), kind=WORKER.name, title="a fix")
    )

    # The session's branch, as its push left it on the private repository.
    branch = rules.session_branch(session.id)
    seed = private_git.root.parent / "seed"
    git(seed, "checkout", "-q", "-b", branch)
    (seed / "total.py").write_text("TOTAL = 3\n")
    git(seed, "add", "total.py")
    git(seed, "-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-qm", "2")
    git(seed, "push", "-q", remote, branch)
    pushed = git(seed, "rev-parse", "HEAD")

    # With no credential, a private repository reads as unavailable, and no
    # workspace is checked out of it.
    with pytest.raises(Unavailable):
        await managers.tools.prepare_workspace(owner, session.id, DIRECTORY)
    assert private_git.authorized == 0 and private_git.refused > 0

    # A wrong one too, and its value is in no message.
    wrong = FetchCredential(username=USER, password=SecretStr("not-the-password"))
    await managers.workspaces.put_fetch_credential(owner, projects.project_id, wrong)
    with pytest.raises(Unavailable) as refused:
        await managers.tools.prepare_workspace(owner, session.id, DIRECTORY)
    assert "not-the-password" not in str(refused.value)

    credential = FetchCredential(username=USER, password=SecretStr(PASSWORD))
    record = await managers.workspaces.put_fetch_credential(owner, projects.project_id, credential)
    assert record.version == 2
    workspace = await managers.tools.prepare_workspace(owner, session.id, DIRECTORY)
    here = Path(workspace.location)
    (here / "notes.txt").write_text("the agent's own work\n")
    delivered = await managers.workspaces.delivery(owner, workspace)
    assert (delivered.base, delivered.head, delivered.changed) == (main, pushed, ("total.py",))
    assert private_git.authorized > 0, "read with the fetch credential"

    # Nothing in the workspace holds it: not its value, nor the header made
    # of it.
    header = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    found = grep(here, PASSWORD, header)
    assert found.returncode == 1 and found.stdout == "", found.stdout
    held = await managers.workspaces.get_workspace(owner, session.id)
    assert PASSWORD not in held.model_dump_json()


async def test_a_session_works_a_private_repository_with_no_credential_in_its_workspace(
    tmp_path: Path, storage: StoragePostgresImpl, private_git: PrivateGit
) -> None:
    main, remote = a_delivery(private_git.root)
    projects = ProjectsTwin(repository=private_git.url)
    forge = IntegrationTwinImpl("forge", writes=True, credential=(WRITER, WRITER_PASSWORD))
    infra = HostInfra(tmp_path / "host")
    managers: Managers = build_managers(
        storage,
        infra,
        agent_kinds=(ENGINEER,),
        platform_agents=PlatformAgents(corpus=CORPUS),
        workspace_projects=projects,
        workspace_reader=on_loopback(),
        source_control=SourceControlForgeImpl(lambda name: forge),
    )
    owner, _ = await managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP),
        "Ajax",
        f"ajax-{new_id().hex[-8:]}",
        f"ann-{new_id().hex[-8:]}@example.test",
        "Ann",
    )
    credential = FetchCredential(username=USER, password=SecretStr(PASSWORD))
    await managers.workspaces.put_fetch_credential(owner, projects.project_id, credential)
    session = await managers.agents.start_session(
        owner, Start(id=new_id(), kind=ENGINEER.name, title="a fix")
    )
    branch = rules.session_branch(session.id)

    # The checkout came in from the platform's bundle: the session's branch,
    # cut from the default branch.
    workspace = await managers.tools.prepare_workspace(owner, session.id, DIRECTORY)
    here = Path(workspace.location)
    assert (git(here, "symbolic-ref", "--short", "HEAD"), git(here, "rev-parse", "HEAD")) == (
        branch,
        main,
    )
    assert (here / "README.md").read_text() == "the project\n"
    assert private_git.authorized > 0, "read with the fetch credential, by the platform"

    # The agent's work: a commit on its branch, and a branch, a tag, and a
    # default branch of its own beside it.
    (here / "total.py").write_text("TOTAL = 3\n")
    git(here, "add", "total.py")
    git(here, "-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-qm", "2")
    head = git(here, "rev-parse", "HEAD")
    git(here, "branch", "other")
    git(here, "tag", "v9")
    git(here, "update-ref", "refs/heads/main", head)

    token = await managers.workspaces.mint_push_token(owner, session.id)
    opened = await managers.workspaces.open_pull_request(
        owner, session.id, token.token.get_secret_value(), head, "Add the total", ""
    )
    assert forge.pull_requests[0].id == opened.id

    # Its commits reached the repository on its own branch alone.
    held = git(Path(remote), "for-each-ref", "--format=%(refname) %(objectname)")
    assert held.splitlines() == [f"refs/heads/main {main}", f"refs/heads/{branch} {head}"]

    # Its delivery reads with its commits, with the fetch credential.
    delivered = await managers.workspaces.delivery(owner, workspace)
    assert (delivered.base, delivered.head, delivered.changed, delivered.dirty) == (
        main,
        head,
        ("total.py",),
        False,
    )

    # Nothing in the workspace holds a credential, so nothing in it reaches
    # the repository on its own.
    headers = [
        base64.b64encode(f"{name}:{value}".encode()).decode()
        for name, value in ((USER, PASSWORD), (WRITER, WRITER_PASSWORD))
    ]
    found = grep(here, PASSWORD, WRITER_PASSWORD, *headers)
    assert found.returncode == 1 and found.stdout == "", found.stdout
    assert not fetches(here), "the workspace cannot read the repository itself"

    # Work left uncommitted is kept on a snapshot as the instance goes.
    (here / "draft.txt").write_text("unfinished\n")
    await managers.tools.release_workspace(owner, workspace)
    kept = git(Path(remote), "for-each-ref", "--format=%(refname)", "refs/snapshots")
    assert kept.startswith(f"refs/snapshots/{branch}/"), kept
