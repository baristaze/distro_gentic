"""A private repository's work product, read over Postgres as a process wires
it: the repository is served by git's own HTTP backend behind basic
authentication, the project's fetch credential is given to the platform and
kept in the tenant's store, and the read hands it to its own git alone. The
session's workspace, a directory on this host, never holds it."""

import base64
import shutil
import subprocess
import sys
import threading
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
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
from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.agents.types.request import Start
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext
from acme.om.exceptions import Unavailable
from acme.om.root import Managers, build_managers
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings
from acme.om.workspaces import rules
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
USER, PASSWORD = "reader", "fetch-only-5f1c0e9a7d"


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


class PrivateGit(ThreadingHTTPServer):
    """Git's HTTP backend over the repositories under `root`, answering only a
    request that carries `USER` and `PASSWORD`; it counts the requests that
    did."""

    def __init__(self, root: Path) -> None:
        super().__init__(("127.0.0.1", 0), PrivateGitHandler)
        self.root = root
        self.expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
        self.authorized = 0
        self.refused = 0

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host!s}:{port}/ajax/app.git"


class PrivateGitHandler(BaseHTTPRequestHandler):
    server: PrivateGit

    def do_GET(self) -> None:
        self._serve()

    def do_POST(self) -> None:
        self._serve()

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _serve(self) -> None:
        if self.headers.get("Authorization") != self.server.expected:
            self.server.refused += 1
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="git"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.server.authorized += 1
        path, _, query = self.path.partition("?")
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        env = {
            "PATH": str(Path(GIT or "git").parent),
            "GIT_PROJECT_ROOT": str(self.server.root),
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
    workspace = await managers.tools.prepare_workspace(owner, session.id, DIRECTORY)
    here = Path(workspace.location)
    (here / "notes.txt").write_text("the agent's own work\n")

    # The session's branch, as its push left it on the private repository.
    branch = rules.session_branch(session.id)
    seed = private_git.root.parent / "seed"
    git(seed, "checkout", "-q", "-b", branch)
    (seed / "total.py").write_text("TOTAL = 3\n")
    git(seed, "add", "total.py")
    git(seed, "-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-qm", "2")
    git(seed, "push", "-q", remote, branch)
    pushed = git(seed, "rev-parse", "HEAD")

    # With no credential, a private repository reads as unavailable.
    with pytest.raises(Unavailable):
        await managers.workspaces.delivery(owner, workspace)
    assert private_git.authorized == 0 and private_git.refused > 0

    # A wrong one too, and its value is in no message.
    wrong = FetchCredential(username=USER, password=SecretStr("not-the-password"))
    await managers.workspaces.put_fetch_credential(owner, projects.project_id, wrong)
    with pytest.raises(Unavailable) as refused:
        await managers.workspaces.delivery(owner, workspace)
    assert "not-the-password" not in str(refused.value)

    credential = FetchCredential(username=USER, password=SecretStr(PASSWORD))
    record = await managers.workspaces.put_fetch_credential(owner, projects.project_id, credential)
    assert record.version == 2
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
