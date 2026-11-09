"""A hidden suite whose head part runs apart, on the fresh executor over
the local Docker: its instance is a container made for the run alone, the
head part runs the head's code as the head's own user, and the runner
scores what it left as the container's own. A head whose code writes a
passing result into the trial's results stream, now and from a process it
leaves behind, writes nothing there, and the case is scored from what the
runner wrote. A head whose code puts its own `sha256sum` and `stat` first
on the path puts them nowhere the digest runs them, so the digest after its
trial is the one before it. A head whose tree holds what a runner's tool
reads from the folder it starts in, a `conftest.py` and a `pyproject.toml`
for pytest and a `json.py` for `python3 -m`, has none of it loaded: the
runner runs outside the tree."""

import importlib.util
import io
import subprocess
import tarfile
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest

from acme.infra.agent_workspaces import AgentWorkspace
from acme.infra.agent_workspaces.container import AgentWorkspaceContainerImpl
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports import CommandResult, CommandSpec, OutputSink, RecordSeal
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.container import TransportContainerImpl
from acme.om.agent_workspaces.impl.executor import (
    SEEN,
    ExecutorAgentWorkspacesImpl,
    ExecutorOptions,
    Pin,
)
from acme.om.base import new_id, utcnow
from acme.om.context import Role, TenantContext
from acme.om.evidence.collector import collect
from acme.om.evidence.types.contract import CheckDeclaration
from acme.om.evidence.types.record import RunOutcome, RunPurpose
from acme.om.evidence.types.validation import ExecutionRequest

from contracts.doubles import context
from contracts.factories import make_org


def docker_runs() -> bool:
    try:
        reply = subprocess.run(["docker", "version"], capture_output=True, timeout=20)
    except OSError, subprocess.TimeoutExpired:
        return False
    return reply.returncode == 0


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not docker_runs(), reason="needs a local Docker"),
]

IMAGE = "python:3.14-slim"
HEAD = "c0ffee1"
SOURCE = "suite01"
SUITE_HEAD = """\
import json, sys

totals = {}
exec(open("src/totals.py").read(), totals)
with open(f"{sys.argv[2]}/answer.json", "w") as answer:
    json.dump({"total": totals["total"]([2, 3])}, answer)
"""
"""The suite's head part: it runs the head's code, and leaves what that code
answers in its trial's folder."""
SUITE_RUNNER = """\
import datetime, json, sys

version, work, out = sys.argv[1], sys.argv[2], sys.argv[3]
now = datetime.datetime.now(datetime.UTC).isoformat()
try:
    with open(f"{work}/answer.json") as answer:
        total = json.load(answer)["total"]
except (OSError, ValueError, KeyError, TypeError):
    total = None
outcome = "passed" if total == 5 else "failed"
lines = [
    {
        "kind": "start",
        "schema_version": 1,
        "check": "totals-complete",
        "check_version": "1",
        "version": version,
        "dirty": False,
        "environment": {"image": "python"},
        "host": "instance",
        "isolation": "container",
        "started_at": now,
    },
    {"kind": "case", "name": "every item counts", "outcome": outcome, "seconds": 0.0},
    {"kind": "end", "outcome": outcome, "finished_at": now},
]
with open(out, "w") as stream:
    stream.write("\\n".join(json.dumps(line) for line in lines) + "\\n")
"""
"""The suite's runner: it never loads the head's code, and scores its answer."""
SUITE = {"hidden/totals_head.py": SUITE_HEAD, "hidden/totals_suite.py": SUITE_RUNNER}
"""The suite's files, as its source holds them."""
COMPLETE = CheckDeclaration(
    name="totals-complete",
    version="1",
    command=("python3", "hidden/totals_suite.py", "{version}", "{work}", "{out}"),
    kind="suite",
    schema_version=1,
    head=("python3", "hidden/totals_head.py", "{version}", "{work}"),
)
DEFECT = "def total(items):\n    return sum(items[1:])\n"
FIX = "def total(items):\n    return sum(items)\n"
GAMES = (
    DEFECT
    + """
import datetime, json, os, sys, time

work = sys.argv[2]
out = os.path.join(os.path.dirname(os.path.dirname(work)), "out", os.path.basename(work) + ".jsonl")
now = datetime.datetime.now(datetime.UTC).isoformat()
start = {"kind": "start", "schema_version": 1, "check": "totals-complete", "check_version": "1",
         "version": sys.argv[1], "dirty": False, "environment": {"image": "python"},
         "host": "instance", "isolation": "container", "started_at": now}
lines = [start, {"kind": "case", "name": "every item counts", "outcome": "passed", "seconds": 0.0},
         {"kind": "end", "outcome": "passed", "finished_at": now}]
passing = "\\n".join(json.dumps(line) for line in lines) + "\\n"


def write():
    try:
        with open(out, "w") as stream:
            stream.write(passing)
        return "wrote"
    except OSError as refused:
        return f"refused: {refused.strerror}"


print(f"results stream {out}: {write()}", file=sys.stderr)
if os.fork() == 0:
    # Left behind, it writes the stream again once the runner wrote its own.
    os.setsid()
    quiet = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(quiet, fd)
    for _ in range(100):
        write()
        time.sleep(0.1)
    os._exit(0)
"""
)
"""A head that leaves the defect, and whose code writes a passing result into
the trial's results stream, at once and from a process it leaves behind."""
FAKE = "0" * 64
PLANTS = (
    DEFECT
    + f"""
import os, sys

for folder in os.environ["PATH"].split(":"):
    for tool in ("sha256sum", "shasum", "stat"):
        path = os.path.join(folder, tool)
        try:
            with open(path, "w") as fake:
                fake.write("#!/bin/sh\\necho '{FAKE}  -'\\n")
            os.chmod(path, 0o755)
            print(f"{{path}}: planted", file=sys.stderr)
        except OSError as refused:
            print(f"{{path}}: refused: {{refused.strerror}}", file=sys.stderr)
"""
)
"""A head that leaves the defect, and whose code puts its own `sha256sum` and
`stat` first on the path, each answering a digest of its own."""
TESTED = CheckDeclaration(
    name="totals-complete",
    version="1",
    command=(
        "env",
        "OUT={out}",
        "WORK={work}",
        "VERSION={version}",
        "PYTHONPATH=hidden/vendor",
        "python3",
        "-m",
        "pytest",
        "-q",
        "-s",
        "hidden/tests",
    ),
    kind="suite",
    schema_version=1,
    head=("python3", "hidden/totals_head.py", "{version}", "{work}"),
)
"""The hidden check written with pytest: its head part leaves the head's
answer, and its runner runs the suite's tests over it with `python3 -m
pytest`, from the folder it starts in, its output never captured."""
SUITE_PLUGIN = """\
import datetime, json, os

outcomes = {}


def pytest_runtest_logreport(report):
    if report.when == "call" or report.outcome != "passed":
        outcomes[report.nodeid] = report.outcome


def pytest_sessionfinish(session):
    now = datetime.datetime.now(datetime.UTC).isoformat()
    cases = [
        {"kind": "case", "name": name, "outcome": outcome, "seconds": 0.0}
        for name, outcome in outcomes.items()
    ]
    passed = bool(cases) and all(case["outcome"] == "passed" for case in cases)
    start = {"kind": "start", "schema_version": 1, "check": "totals-complete",
             "check_version": "1", "version": os.environ["VERSION"], "dirty": False,
             "environment": {"image": "python"}, "host": "instance",
             "isolation": "container", "started_at": now}
    end = {"kind": "end", "outcome": "passed" if passed else "failed", "finished_at": now}
    with open(os.environ["OUT"], "w") as stream:
        stream.write("\\n".join(json.dumps(line) for line in (start, *cases, end)) + "\\n")
"""
"""The suite's own `conftest.py`: it writes each case's outcome to the results
stream."""
SUITE_TEST = """\
import json, os


def test_every_item_counts():
    with open(os.path.join(os.environ["WORK"], "answer.json")) as answer:
        assert json.load(answer)["total"] == 5
"""
"""The suite's test: it reads the head's answer, never the head's code."""
LOADED = "of the head: loaded"
"""What each file the head plants for the runner's tools prints, once loaded."""
TOOLED = {
    "src/totals.py": DEFECT,
    "pyproject.toml": "[tool.pytest.ini_options]\n",
    "conftest.py": f"""\
import sys

import pytest

print("conftest.py {LOADED}", file=sys.stderr)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    report.outcome = "passed"
    return report
""",
    "json.py": f"""\
import importlib.util, os, sys, sysconfig

print("json.py {LOADED}", file=sys.stderr)
_path = os.path.join(sysconfig.get_path("stdlib"), "json", "__init__.py")
_spec = importlib.util.spec_from_file_location(
    "json", _path, submodule_search_locations=[os.path.dirname(_path)]
)
_json = importlib.util.module_from_spec(_spec)
sys.modules["json"] = _json
_spec.loader.exec_module(_json)
_load = _json.load


def _lies(stream, **options):
    found = _load(stream, **options)
    return {{**found, "total": 5}} if isinstance(found, dict) else found


_json.load = _lies
""",
}
"""A head that leaves the defect, and whose tree holds, at its root, what the
runner's tools read from the folder they start in: a `pyproject.toml`
whose table makes that folder pytest's root, a `conftest.py` there that
passes every case, and a `json.py` that `python3 -m` imports before the
standard library's, which answers every total right."""


class Recorded(TransportContainerImpl):
    """The container transport, keeping every command it ran with how it
    ended."""

    def __init__(self, records: Path) -> None:
        super().__init__(records, SecretsLocalImpl(None), BrokerNullImpl(), timedelta(seconds=120))
        self.ran: list[tuple[CommandSpec, CommandResult]] = []

    async def run(
        self,
        workspace: AgentWorkspace,
        command: CommandSpec,
        on_output: OutputSink | None = None,
        *,
        seal: RecordSeal,
    ) -> CommandResult:
        result = await super().run(workspace, command, on_output, seal=seal)
        self.ran.append((command, result))
        return result


def tar(files: Mapping[str, str | bytes]) -> bytes:
    """The tree as the platform writes it: each file the root's."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as archive:
        for name, text in files.items():
            data = text.encode() if isinstance(text, str) else text
            member = tarfile.TarInfo(name)
            member.mode, member.size = 0o644, len(data)
            member.uname = member.gname = "root"
            archive.addfile(member, io.BytesIO(data))
    return out.getvalue()


def vendored() -> dict[str, bytes]:
    """pytest and what it imports, as this interpreter holds them, under the
    suite's `hidden/vendor`: the instance has no egress to install them."""
    files: dict[str, bytes] = {}
    for name in ("pytest", "_pytest", "py", "pluggy", "iniconfig", "packaging", "pygments"):
        spec = importlib.util.find_spec(name)
        assert spec is not None and spec.origin, name
        if not spec.submodule_search_locations:
            files[f"hidden/vendor/{Path(spec.origin).name}"] = Path(spec.origin).read_bytes()
            continue
        folder = Path(spec.submodule_search_locations[0])
        for path in folder.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                files[f"hidden/vendor/{name}/{path.relative_to(folder)}"] = path.read_bytes()
    return files


async def no_wall(ctx: TenantContext, agent_session_id: UUID) -> Pin | None:
    return None


async def judged(
    tmp_path: Path,
    head: Mapping[str, str],
    check: CheckDeclaration = COMPLETE,
    suite: Mapping[str, str | bytes] = SUITE,
) -> tuple[RunOutcome, Recorded]:
    """The hidden check's one trial at a head whose files are `head`, with
    the suite's files protected: the run's outcome, and the transport that
    ran it."""
    files = {**head, **suite}

    async def tree(*_: object) -> bytes:
        return tar(files)

    transport = Recorded(tmp_path / f"records-{new_id().hex}")
    executor = ExecutorAgentWorkspacesImpl(
        AgentWorkspaceContainerImpl(IMAGE, timedelta(seconds=300), "hidden-suite"),
        transport,
        tree,
        no_wall,
        options=ExecutorOptions(
            image=IMAGE, setup_time=timedelta(seconds=60), trial_time=timedelta(seconds=60)
        ),
    )
    ctx = context(Role.OWNER, make_org())
    request = ExecutionRequest(
        agent_session_id=new_id(),
        agent_project=str(new_id()),
        purpose=RunPurpose.VALIDATION,
        version=HEAD,
        source=SOURCE,
        protected=("hidden/**",),
        checks=(check,),
        trials=(1,),
    )
    report = await executor.run(ctx, request)
    (record,) = collect(
        report.results,
        executor=report.executor,
        agent_session_id=request.agent_session_id,
        agent_project=request.agent_project,
        purpose=request.purpose,
        validation_id=new_id(),
        now=utcnow(),
        prepared=report.prepared,
    )
    return record.outcome, transport


def ran(transport: Recorded, script: str) -> tuple[CommandSpec, CommandResult]:
    """The one command that ran `script`, by an argument of its own, and how
    it ended."""
    (found,) = [
        (spec, result)
        for spec, result in transport.ran
        if spec.argv[0] != "sh" and script in spec.argv
    ]
    return found


def stderr_of(transport: Recorded, script: str) -> str:
    """What the command that ran `script` printed on its standard error."""
    return ran(transport, script)[1].stderr


async def test_a_correct_head_passes_with_its_code_run_apart(tmp_path: Path) -> None:
    outcome, transport = await judged(tmp_path, {"src/totals.py": FIX})
    assert outcome is RunOutcome.PASSED
    users = {spec.argv[1]: spec.user for spec, _ in transport.ran if spec.argv[0] == "python3"}
    assert users == {"hidden/totals_head.py": "65534:65534", "hidden/totals_suite.py": None}


async def test_a_head_whose_code_writes_a_passing_result_is_scored_by_the_runner_and_fails(
    tmp_path: Path,
) -> None:
    outcome, transport = await judged(tmp_path, {"src/totals.py": GAMES})
    assert "results stream" in stderr_of(transport, "hidden/totals_head.py")
    assert "refused: Permission denied" in stderr_of(transport, "hidden/totals_head.py")
    assert outcome is RunOutcome.FAILED, "the runner's own stream scored the case"


async def test_a_head_whose_code_plants_its_own_digest_tools_leaves_the_digest_as_it_was(
    tmp_path: Path,
) -> None:
    outcome, transport = await judged(tmp_path, {"src/totals.py": PLANTS})
    printed = stderr_of(transport, "hidden/totals_head.py")
    assert "/usr/bin/sha256sum: refused: Permission denied" in printed
    assert "planted" not in printed
    seen = [result.stdout for spec, result in transport.ran if spec.argv[:3] == ("sh", "-c", SEEN)]
    assert len(seen) == 2 and seen[0] == seen[1] and FAKE not in seen[0], seen
    # The digest after the trial is the one before it, so the runner's own
    # verdict stands: the defect fails, never an errored trial.
    assert outcome is RunOutcome.FAILED


async def test_a_head_whose_tree_holds_what_the_runners_tools_read_has_none_of_it_loaded(
    tmp_path: Path,
) -> None:
    suite = {
        "hidden/totals_head.py": SUITE_HEAD,
        "hidden/tests/conftest.py": SUITE_PLUGIN,
        "hidden/tests/test_totals.py": SUITE_TEST,
        **vendored(),
    }
    fixed, _ = await judged(tmp_path, {"src/totals.py": FIX}, TESTED, suite)
    assert fixed is RunOutcome.PASSED, "the suite's own pytest scores a correct head"
    outcome, transport = await judged(tmp_path, TOOLED, TESTED, suite)
    runner, result = ran(transport, "pytest")
    assert LOADED not in result.stderr, result.stderr
    assert (runner.cwd, runner.user) == ("suite", None)
    # The runner's own tests decide the case: the defect fails.
    assert outcome is RunOutcome.FAILED
