"""A project's repository on this disk, for the suites that run a
delivery's checks for real: its base holds a cart, the runner its `unit`
check runs, and the fixture the runner reads; a delivered head is cut from
the base and served bare beside it, and every project binds it."""

import os
import subprocess
from pathlib import Path
from uuid import UUID

from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.context import TenantContext
from acme.om.evidence.types.contract import CheckDeclaration
from acme.om.workspaces.projects import WorkspaceProjectsInterface
from acme.om.workspaces.types.source import RepositoryBinding

AUTHOR = {
    "GIT_AUTHOR_NAME": "Ann",
    "GIT_AUTHOR_EMAIL": "ann@ajax.test",
    "GIT_COMMITTER_NAME": "Ann",
    "GIT_COMMITTER_EMAIL": "ann@ajax.test",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
RUNNER = """\
import datetime, json, os, sys

version, out = sys.argv[1], sys.argv[2]
now = datetime.datetime.now(datetime.UTC).isoformat()
expected = int(open("checks/expected.txt").read())
cart = {}
exec(open("src/cart.py").read(), cart)
outcome = "passed" if cart.get("TOTAL") == expected else "failed"
lines = [
    {
        "kind": "start",
        "schema_version": 1,
        "check": "unit",
        "check_version": "1",
        "version": version,
        "dirty": False,
        "environment": {"image": "python", "toolchain": {"python": sys.version.split()[0]}},
        "host": os.uname().nodename,
        "isolation": "container" if os.path.exists("/.dockerenv") else "none",
        "started_at": now,
    },
    {"kind": "case", "name": "the cart's total", "outcome": outcome, "seconds": 0.0},
    {"kind": "end", "outcome": outcome, "finished_at": now},
]
with open(out, "w") as stream:
    stream.write("\\n".join(json.dumps(line) for line in lines) + "\\n")
"""
"""The base's runner: the cart's total against the base's fixture."""

UNIT = CheckDeclaration(
    name="unit",
    version="1",
    command=("python3", "checks/run.py", "{version}", "{out}"),
    kind="suite",
    schema_version=1,
)


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"], "HOME": str(repo), **AUTHOR},
    )
    return done.stdout.decode().strip()


def commit(repo: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change")
    return git(repo, "rev-parse", "HEAD")


class Repository:
    """A project's repository on this disk, served bare: its base holds the
    cart, the runner, and the fixture."""

    def __init__(self, root: Path) -> None:
        self.work = root / "work"
        self.served = root / "served.git"
        self.work.mkdir()
        git(self.work, "init", "-q", "-b", "main")
        self.base = commit(
            self.work,
            {"src/cart.py": "TOTAL = 2\n", "checks/run.py": RUNNER, "checks/expected.txt": "3\n"},
        )

    def deliver(self, files: dict[str, str]) -> str:
        """The delivered head, on a branch cut from the base, and the
        repository served with it."""
        git(self.work, "checkout", "-q", "-b", "delivery", self.base)
        head = commit(self.work, files)
        git(self.work.parent, "clone", "-q", "--bare", str(self.work), str(self.served))
        return head


class OnDisk(WorkspaceProjectsInterface):
    """Every project binds the repository on this disk."""

    def __init__(self, repository: Repository) -> None:
        self._url = f"file://{repository.served}"

    async def project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        return None

    async def binding_of(self, ctx: TenantContext, project_id: UUID) -> RepositoryBinding | None:
        return RepositoryBinding(project_id=project_id, repository=self._url)
