"""A hidden suite from a source of its own reaches the fresh executor: the
harness asks for it by the project whose repository holds it, the platform
reads the tree at the head with every path of the suite taken from that
repository, and the suite's own files run there, whatever the head holds
at those paths. Both repositories are on this disk, read by their URLs;
the instance is the twins', and each check's command runs for real in
the tree the executor wrote into it."""

import asyncio
import io
import os
import subprocess
import sys
import tarfile
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from contracts.acceptance import surfaces
from contracts.doubles import context
from contracts.evidence import evidence_over
from contracts.factories import make_org

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.transports import CommandSpec
from acme.infra.transports.twin import TransportTwinImpl, TwinReply
from acme.infra.workspaces import IsolationMode, IsolationSpec, Workspace
from acme.infra.workspaces.twin import WorkspaceTwinImpl
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents.types.result import Claim, Result
from acme.om.base import new_id
from acme.om.context import Role, TenantContext
from acme.om.evidence.impl.harness import AcceptanceHarnessImpl
from acme.om.evidence.types.acceptance import AcceptanceVerdict, HiddenSuite, Link, Scenario
from acme.om.evidence.types.contract import CheckDeclaration
from acme.om.evidence.types.validation import Delivery
from acme.om.root import build_managers
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.workspaces.impl.executor import ARCHIVE, ExecutorOptions, ExecutorWorkspacesImpl
from acme.om.workspaces.impl.reader import RepositoryReaderGitImpl
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
SUITE_RUNNER = """\
import datetime, json, sys

version, out = sys.argv[1], sys.argv[2]
now = datetime.datetime.now(datetime.UTC).isoformat()
totals = {}
exec(open("src/totals.py").read(), totals)
outcome = "passed" if totals["total"]([2, 3]) == 5 else "failed"
lines = [
    {
        "kind": "start",
        "schema_version": 1,
        "check": "totals-complete",
        "check_version": "1",
        "version": version,
        "dirty": False,
        "environment": {"image": "python", "toolchain": {"python": sys.version.split()[0]}},
        "host": "instance",
        "isolation": "twin",
        "started_at": now,
    },
    {"kind": "case", "name": "every item counts", "outcome": outcome, "seconds": 0.0},
    {"kind": "end", "outcome": outcome, "finished_at": now},
]
with open(out, "w") as stream:
    stream.write("\\n".join(json.dumps(line) for line in lines) + "\\n")
"""
"""The hidden suite's runner, in its own repository: every item of a list
counts toward its total."""
SCORED_RUNNER = SUITE_RUNNER.replace(
    'outcome = "passed" if totals["total"]([2, 3]) == 5 else "failed"',
    'score = {}\nexec(open("checks/score.py").read(), score)\n'
    'outcome = "passed" if score["passes"](totals["total"]) else "failed"',
)
"""A hidden suite's runner whose cases the project's own code scores, at a
path the scenario forbids."""
SCORE = "def passes(total):\n    return total([2, 3]) == 5\n"
GAMED = "def passes(total):\n    return True\n"
"""What a head writes over the code that scores the suite: every case passes."""
PLANTED = SUITE_RUNNER.replace('totals["total"]([2, 3]) == 5', "True")
"""A runner a head plants where the hidden suite's sits: it passes whatever
the code does."""
DEFECT = "def total(items):\n    return sum(items[1:])\n"
FIX = "def total(items):\n    return sum(items)\n"
COMPLETE = CheckDeclaration(
    name="totals-complete",
    version="1",
    command=("python3", "hidden/totals_suite.py", "{version}", "{out}"),
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


def commit(repo: Path, files: Mapping[str, str]) -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change")
    return git(repo, "rev-parse", "HEAD")


def served(work: Path) -> str:
    """The repository at `work`, served bare beside it, by its URL."""
    bare = work.parent / f"{work.name}.git"
    git(work.parent, "clone", "-q", "--bare", str(work), str(bare))
    return f"file://{bare}"


class Bound(WorkspaceProjectsInterface):
    """Each project binds the repository on this disk the case gave it."""

    def __init__(self, urls: Mapping[UUID, str]) -> None:
        self._urls = urls

    async def project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        return None

    async def binding_of(self, ctx: TenantContext, project_id: UUID) -> RepositoryBinding | None:
        url = self._urls.get(project_id)
        return None if url is None else RepositoryBinding(project_id=project_id, repository=url)


class Instances(WorkspaceTwinImpl):
    """The twin provider, keeping the last instance it made."""

    made: Workspace | None = None

    async def prepare(self, org_id: UUID, workspace_id: UUID, spec: IsolationSpec) -> Workspace:
        self.made = await super().prepare(org_id, workspace_id, spec)
        return self.made


class Ran:
    """An instance's commands run for real: the tree the executor wrote is
    unpacked in a directory of its own, and each check runs there, its
    results stream handed back to the transport where the executor reads
    it. `trees` keeps each tree's files, as the executor wrote them."""

    def __init__(self, root: Path, provider: Instances, transport: TransportTwinImpl) -> None:
        self._root = root
        self._provider = provider
        self._transport = transport
        self.trees: list[dict[str, bytes]] = []
        transport.handler = self._answer

    async def _answer(self, command: CommandSpec, env: Mapping[str, str]) -> TwinReply:
        workspace = self._provider.made
        assert workspace is not None
        instance = self._root / str(workspace.id)
        if command.argv[0] == "sh":
            tar = await self._transport.read_file(workspace, ARCHIVE, 1 << 24)
            with tarfile.open(fileobj=io.BytesIO(tar)) as archive:
                members = [member for member in archive if member.isfile()]
                files = {m.name: archive.extractfile(m).read() for m in members}  # pyright: ignore[reportOptionalMemberAccess]
            self.trees.append(files)
            for name, data in files.items():
                (instance / "tree" / name).parent.mkdir(parents=True, exist_ok=True)
                (instance / "tree" / name).write_bytes(data)
            (instance / "out").mkdir(parents=True)
            return TwinReply(stdout=f"{instance}\n")
        argv = [sys.executable if part == "python3" else part for part in command.argv]
        done = await asyncio.create_subprocess_exec(
            *argv,
            cwd=instance / "tree",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await done.communicate()
        for written in (instance / "out").iterdir():
            await self._transport.write_file(
                workspace, f"out/{written.name}", written.read_bytes(), 1
            )
        return TwinReply(done.returncode or 0, stdout.decode(), stderr.decode())


class Repositories:
    """The scenario's project, whose base holds the defect, and the hidden
    suite's own repository, bound to a project of the same tenant apart
    from it; the executor over the twins, with its tree read by the
    workspaces from both; and the harness over it."""

    def __init__(
        self,
        tmp_path: Path,
        base: Mapping[str, str] | None = None,
        runner: str = SUITE_RUNNER,
        forbidden: tuple[str, ...] = ("hidden/**",),
    ) -> None:
        self.ctx = context(Role.OWNER, make_org())
        self.project_id, self.suite_project_id = new_id(), new_id()
        self.work = tmp_path / "project"
        self.work.mkdir()
        git(self.work, "init", "-q", "-b", "main")
        self.base = commit(self.work, base or {"src/totals.py": DEFECT})
        suite = tmp_path / "suites"
        suite.mkdir()
        git(suite, "init", "-q", "-b", "main")
        self.source = commit(suite, {"hidden/totals_suite.py": runner, "README.md": "the suites"})
        self.suite_url = served(suite)
        self.scenario = Scenario(
            name="totals-drop",
            project=str(self.project_id),
            base=self.base,
            objective="Some carts total less than their items. Make every cart total right.",
            root_cause=("first item",),
            visible=("unit",),
            hidden=HiddenSuite(
                project=str(self.suite_project_id),
                source=self.source,
                paths=("hidden/**",),
                checks=(COMPLETE,),
                markers=("totals-complete", "totals_suite"),
            ),
            forbidden=forbidden,
        )
        infra = InfraLocalImpl(tmp_path / "infra")
        transport = infra.get_transport()
        assert isinstance(transport, TransportTwinImpl)
        provider = Instances()
        self.ran = Ran(tmp_path / "instances", provider, transport)
        self._tmp_path = tmp_path
        self._infra = infra
        self._provider = provider
        self._transport = transport

    async def judge(self, files: Mapping[str, str]) -> AcceptanceVerdict:
        """The verdict on a session that delivered `files` over the base."""
        git(self.work, "checkout", "-q", "-B", "delivery", self.base)
        head = commit(self.work, files)
        bare = self.work.parent / "project.git"
        if bare.exists():
            git(bare, "fetch", "-q", str(self.work), "+delivery:delivery")
            url = f"file://{bare}"
        else:
            url = served(self.work)
        managers = build_managers(
            StorageMemoryImpl(),
            self._infra,
            workspace_projects=Bound({self.project_id: url, self.suite_project_id: self.suite_url}),
            workspace_reader=RepositoryReaderGitImpl(on_disk=True),
        )
        executor = ExecutorWorkspacesImpl(
            self._provider,
            self._transport,
            managers.workspaces.checks_tree,
            no_wall,
            options=ExecutorOptions(isolation=IsolationMode.TWIN),
        )
        evidence = evidence_over()
        session = new_id()
        evidence.work.deliver(
            self.ctx.org_id,
            session,
            Delivery(
                project=str(self.project_id),
                base=self.base,
                head=head,
                changed=tuple(sorted(files)),
            ),
        )
        harness = AcceptanceHarnessImpl(evidence.storage, evidence.work, executor, evidence.gate)
        return await harness.judge(
            self.ctx, self.scenario, session, Result(claim=Claim.SUCCEEDED), surfaces()
        )


async def no_wall(ctx: TenantContext, session_id: UUID) -> IsolationSpec | None:
    """Every session of the case is the cloud's."""
    return None


# Check 2: an acceptance run whose hidden suite names a source of its own
# runs those files, protected, in the fresh executor.


async def test_a_hidden_suite_from_a_source_of_its_own_runs_its_files_protected(
    tmp_path: Path,
) -> None:
    repositories = Repositories(tmp_path)

    # A head that fixes the defect: the suite's own runner, which the
    # project's repository never held, runs in the tree and passes.
    fixed = await repositories.judge({"src/totals.py": FIX})
    assert [(run.check, run.version, run.passing) for run in fixed.hidden] == [
        (COMPLETE.name, fixed.head, True)
    ]
    assert Link.HIDDEN not in fixed.broken()
    (tree,) = repositories.ran.trees
    assert tree == {
        "src/totals.py": FIX.encode(),
        "hidden/totals_suite.py": SUITE_RUNNER.encode(),
    }, "the head's files, and of the suite's repository only the paths its patterns match"

    # A head that leaves the defect and plants a runner where the suite's
    # sits: the suite's own runs in its place, and fails.
    planted = await repositories.judge({"hidden/totals_suite.py": PLANTED})
    assert [(run.check, run.passing) for run in planted.hidden] == [(COMPLETE.name, False)]
    assert repositories.ran.trees[-1]["hidden/totals_suite.py"] == SUITE_RUNNER.encode()
    assert {Link.HIDDEN, Link.UNTOUCHED} <= planted.broken()


# Check 1: a head that rewrites a forbidden path has its hidden run
# executed with the base's copy of that path and the suite's own files.


async def test_a_head_that_rewrites_what_scores_the_suite_is_judged_by_the_bases_copy(
    tmp_path: Path,
) -> None:
    repositories = Repositories(
        tmp_path,
        base={"src/totals.py": DEFECT, "checks/score.py": SCORE},
        runner=SCORED_RUNNER,
        forbidden=("hidden/**", "checks/**"),
    )

    # A head that leaves the defect, rewrites the code that scores the
    # suite, and adds a file where the scenario forbids one: the base's
    # copy scores the suite's own runner, nothing added there runs, and
    # the hidden case fails.
    gamed = await repositories.judge({"checks/score.py": GAMED, "checks/extra.py": GAMED})
    assert [(run.check, run.version, run.passing) for run in gamed.hidden] == [
        (COMPLETE.name, gamed.head, False)
    ]
    assert {Link.HIDDEN, Link.UNTOUCHED} <= gamed.broken()
    (tree,) = repositories.ran.trees
    assert tree == {
        "src/totals.py": DEFECT.encode(),
        "checks/score.py": SCORE.encode(),
        "hidden/totals_suite.py": SCORED_RUNNER.encode(),
    }, "the head's code, the base's forbidden paths, and the suite's own files"

    # A head that fixes the defect passes on the same copy.
    fixed = await repositories.judge({"src/totals.py": FIX})
    assert [(run.check, run.passing) for run in fixed.hidden] == [(COMPLETE.name, True)]
    assert Link.HIDDEN not in fixed.broken()
