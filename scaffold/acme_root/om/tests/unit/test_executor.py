"""The platform's fresh executor, over the twins: each run gets an instance
nobody used before, its tree written in from outside and its checks run
there with their templates filled, and the instance is destroyed after,
whatever ended the run, so nothing of one run is there for the next. A
session inside its tenant's wall runs on an instance a host of its pool
makes, never on the cloud's, and a process that reaches no pool refuses it
before anything is made. A session pinned to its agent project's workspace base has
its checks run on a new instance of that base, with no egress."""

import io
import json
import tarfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from acme.infra.agent_workspaces import (
    AgentWorkspace,
    AgentWorkspaceBase,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
)
from acme.infra.agent_workspaces.twin import AgentWorkspaceTwinImpl
from acme.infra.exceptions import InfraNotFound
from acme.infra.impl.local import InfraLocalImpl
from acme.infra.transports import CommandResult, CommandSpec, TransportInterface
from acme.infra.transports.twin import TransportTwinImpl, TwinHandler, TwinReply
from acme.om.agent_workspaces.impl import executor as executor_module
from acme.om.agent_workspaces.impl.executor import ExecutorAgentWorkspacesImpl, ExecutorOptions, Pin
from acme.om.agent_workspaces.placed import PlacedInstancesInterface
from acme.om.base import new_id, utcnow
from acme.om.context import Role, TenantContext
from acme.om.evidence.collector import collect, digest
from acme.om.evidence.types.contract import CheckDeclaration
from acme.om.evidence.types.provenance import Provenance
from acme.om.evidence.types.rate import RateRule
from acme.om.evidence.types.record import ExecutionRecord, RunOutcome, RunPurpose
from acme.om.evidence.types.validation import ExecutionRequest, ExecutorReport
from acme.om.exceptions import Unavailable

from contracts.doubles import context
from contracts.evidence import stream
from contracts.factories import make_org

HEAD = "c" * 40
BASE = "b" * 40


def a_tree() -> bytes:
    """The tree the executor writes into each instance, as a tar: the
    checks' runner, at a path the request protects."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as archive:
        archive.addfile(tarfile.TarInfo("checks/run.py"), io.BytesIO(b""))
    return out.getvalue()


TAR = a_tree()
PINNED = IsolationSpec(mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.OPEN))
"""A directory on a host of the session's pool, as its session is pinned."""
AGENT_WORKSPACE_BASE = AgentWorkspaceBase(
    image="registry.example/toolchain:3",
    setup=("pip install --target /opt/deps numpy",),
    egress=EgressPolicy(mode=EgressMode.OPEN),
)
"""An agent project's workspace base, as its session's pin names it: an image, and a
setup that reaches a package registry."""
ON_WORKSPACE_BASE = IsolationSpec(
    mode=IsolationMode.CONTAINER,
    egress=EgressPolicy(mode=EgressMode.NONE),
    base=AGENT_WORKSPACE_BASE,
)
"""A session pinned to its agent project's workspace base, in a container with no
egress, as the software engineer's is."""
WORKSPACE_BASE_SNAPSHOT = b"the workspace base, once its setup ran"
"""The base's snapshot, as the tenant keeps it: what the setup installed."""
HOSTED = b"the workspace base, as the host built it"
"""The base's snapshot, as a host of the session's pool keeps it."""
ROOT = "/instance"
CHECK = CheckDeclaration(
    name="unit",
    version="1",
    command=("python3", "checks/run.py", "--at", "{version}", "--out={out}"),
    kind="suite",
    schema_version=1,
)


class Instances(AgentWorkspaceTwinImpl):
    """The twin provider, keeping every instance it made, in order, and the
    snapshot and the base's snapshot each started from."""

    def __init__(self) -> None:
        super().__init__()
        self.made: list[AgentWorkspace] = []
        self.started: list[tuple[bytes | None, bytes | None]] = []

    async def prepare(
        self,
        org_id: UUID,
        agent_workspace_id: UUID,
        spec: IsolationSpec,
        snapshot: bytes | None = None,
        base: bytes | None = None,
        *,
        building: bool = False,
    ) -> AgentWorkspace:
        workspace = await super().prepare(
            org_id, agent_workspace_id, spec, snapshot, base, building=building
        )
        self.made.append(workspace)
        self.started.append((snapshot, base))
        return workspace


class Pool(PlacedInstancesInterface):
    """A host of a pinned session's pool, as the twins play it: the
    instances it is asked for, each with the session and the spec it was
    asked at, made over `provider` and reached by `transport`, and the ones
    it is asked to destroy. One on a base with setup starts from the base
    the host keeps in its own store (`HOSTED`)."""

    def __init__(self, provider: Instances, transport: TransportInterface) -> None:
        self.provider = provider
        self.transport = transport
        self.asked: list[tuple[UUID, UUID, IsolationSpec]] = []
        self.destroyed: list[UUID] = []

    async def make(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        instance_id: UUID,
        spec: IsolationSpec,
        by: datetime,
    ) -> tuple[AgentWorkspace, TransportInterface]:
        self.asked.append((agent_session_id, instance_id, spec))
        played = spec.model_copy(update={"mode": IsolationMode.TWIN})
        base = HOSTED if spec.base is not None and spec.base.setup else None
        made = await self.provider.prepare(ctx.org_id, instance_id, played, base=base)
        return made, self.transport

    async def destroy(self, ctx: TenantContext, instance_id: UUID, spec: IsolationSpec) -> None:
        self.destroyed.append(instance_id)
        await self.provider.purge(ctx.org_id, instance_id)


class Executor:
    """The executor over the twins, a runner that writes a passing stream to
    its `{out}`, and what the tree was asked for. A pinned session's runs
    are made by `pool` when it reaches one, and `provider` makes every
    instance either way, so `cloud` is what the cloud's provider made.
    `pin` is what the session pinned, `PINNED` inside the wall unless it
    names another; the tenant's bases answer every base the executor asks
    for with its snapshot, unless `bases` is off."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        pinned: bool = False,
        pool: bool = False,
        max_bytes: int = 1 << 20,
        pin: IsolationSpec | None = None,
        bases: bool = True,
    ) -> None:
        infra = InfraLocalImpl(tmp_path)
        transport = infra.get_transport()
        assert isinstance(transport, TransportTwinImpl)
        self.transport = transport
        self.provider = Instances()
        self.cloud = Instances() if pool else self.provider
        self.pool = Pool(self.provider, transport) if pool else None
        self.trees: list[tuple[UUID, str, str, tuple[str, ...]]] = []
        self.pinned = pinned
        self.pin = pin
        self.bases: list[IsolationSpec] = []
        self.written: list[dict[str, bytes]] = []
        self.transport.handler = self._answer
        self.executor = ExecutorAgentWorkspacesImpl(
            self.cloud,
            transport,
            self._tree,
            self._pinned,
            self.pool,
            ExecutorOptions(isolation=IsolationMode.TWIN, max_results_bytes=max_bytes),
            bases=self._base if bases else None,
        )

    async def _tree(
        self,
        ctx: TenantContext,
        agent_project_id: UUID,
        version: str,
        source: str,
        protected: tuple[str, ...],
        source_agent_project: UUID,
        base: str | None,
        untouched: tuple[str, ...],
    ) -> bytes:
        assert source_agent_project == agent_project_id, (
            "a validation's source is its agent project's own"
        )
        self.trees.append((agent_project_id, version, source, protected))
        return TAR

    async def _pinned(self, ctx: TenantContext, agent_session_id: UUID) -> Pin | None:
        """A pinned session runs in a directory on its pool's host, unless
        its pin names another isolation."""
        if self.pinned:
            return Pin(self.pin or PINNED, walled=True)
        return None if self.pin is None else Pin(self.pin, walled=False)

    async def _base(self, ctx: TenantContext, spec: IsolationSpec) -> bytes:
        """The tenant's snapshot of the base `spec` names, as it keeps it."""
        self.bases.append(spec)
        return WORKSPACE_BASE_SNAPSHOT

    async def _answer(self, command: CommandSpec, env: Mapping[str, str]) -> TwinReply:
        workspace = self.provider.made[-1]
        if command.argv[0] == "sh":
            return TwinReply(stdout=f"{ROOT}\n")
        # What the instance holds when the check starts, a file another run
        # left included; then the check leaves one of its own.
        self.written.append(
            {entry.path: b"" for entry in await self.transport.list_files(workspace, "tree", 100)}
        )
        await self.transport.write_file(workspace, "tree/left-behind", b"agent", 1)
        out = command.argv[-1].removeprefix("--out=")
        lines = stream(CHECK.name, CHECK.version, HEAD, "passed", Provenance.REAL, utcnow())
        written = "\n".join(json.dumps(line) for line in lines).encode()
        await self.transport.write_file(workspace, out.removeprefix(f"{ROOT}/"), written, 1)
        return TwinReply()


def a_request(trials: int = 1) -> ExecutionRequest:
    return ExecutionRequest(
        agent_session_id=new_id(),
        agent_project=str(new_id()),
        purpose=RunPurpose.VALIDATION,
        version=HEAD,
        source=BASE,
        checks=(CHECK,),
        trials=(trials,),
        protected=("checks/**",),
    )


# Check 3: the instance is destroyed after the run, and nothing of it is
# reused by a later run.


async def test_each_run_gets_an_instance_nobody_used_and_destroys_it(tmp_path: Path) -> None:
    harness = Executor(tmp_path)
    ctx = context(Role.OWNER, make_org())
    request = a_request(trials=2)

    first = await harness.executor.run(ctx, request)
    second = await harness.executor.run(ctx, request)

    made = harness.provider.made
    assert len(made) == 2 and made[0].id != made[1].id, "a new instance each run"
    assert harness.provider.live == set(), "every instance is destroyed after its run"
    for workspace in made:
        with pytest.raises(InfraNotFound):
            await harness.transport.read_file(workspace, "tree/left-behind", 10)
    assert [sorted(found) for found in harness.written] == [[], ["tree/left-behind"]] * 2, (
        "a run's second trial finds what its first left, and no run finds another's"
    )
    assert first.executor == f"executor:{made[0].id}" != second.executor
    assert first.sha256 == digest(first.results)
    records = collect(
        first.results,
        executor=first.executor,
        agent_session_id=request.agent_session_id,
        agent_project=request.agent_project,
        purpose=RunPurpose.VALIDATION,
        validation_id=new_id(),
        now=utcnow(),
    )
    assert len(records) == 2 and {r.version for r in records} == {HEAD}
    # The tree came from outside, at the head, with the checks from the base,
    # and each trial ran the template filled, in the tree.
    (agent_project_id, version, source, protected) = harness.trees[0]
    assert (str(agent_project_id), version, source, protected) == (
        request.agent_project,
        HEAD,
        BASE,
        ("checks/**",),
    )
    checks = [c for c in harness.transport.commands if c.argv[0] != "sh"]
    assert [(c.argv, c.cwd, c.env) for c in checks[:2]] == [
        (
            ("python3", "checks/run.py", "--at", HEAD, f"--out={ROOT}/out/0-{trial}.jsonl"),
            "tree",
            (),
        )
        for trial in range(2)
    ]


async def unpacks_nothing(command: CommandSpec, env: Mapping[str, str]) -> TwinReply:
    """An instance whose tree does not unpack: the run ends before a check."""
    return TwinReply(1)


async def test_an_instance_goes_whatever_ended_its_run(tmp_path: Path) -> None:
    harness = Executor(tmp_path)
    ctx = context(Role.OWNER, make_org())

    harness.transport.handler = unpacks_nothing
    with pytest.raises(Unavailable, match="did not unpack"):
        await harness.executor.run(ctx, a_request())
    assert harness.provider.made and harness.provider.live == set()


# Every trial counts: one that ran to no verdict is an errored run the
# executor writes, never a refusal that a later run could hide.


async def test_a_trial_that_wrote_no_results_or_ran_past_its_time_is_an_errored_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Executor(tmp_path)
    ctx = context(Role.OWNER, make_org())
    request = a_request(trials=3)
    answer = harness._answer  # pyright: ignore[reportPrivateUsage]
    trials: list[CommandSpec] = []

    async def crashes_then_hangs_then_passes(
        command: CommandSpec, env: Mapping[str, str]
    ) -> TwinReply:
        if command.argv[0] != "sh":
            trials.append(command)
            if len(trials) == 1:
                return TwinReply(1)  # it crashed before it wrote a line
        return await answer(command, env)

    run = harness.transport.run

    async def second_runs_past_its_time(
        workspace: AgentWorkspace, command: CommandSpec, **kwargs: Any
    ) -> CommandResult:
        result = await run(workspace, command, **kwargs)
        if command.argv[0] != "sh" and len(trials) == 2:
            return result.model_copy(update={"exit_code": None, "timed_out": True})
        return result

    harness.transport.handler = crashes_then_hangs_then_passes
    monkeypatch.setattr(harness.transport, "run", second_runs_past_its_time)
    report = await harness.executor.run(ctx, request)

    records = collected(report, request)
    assert [record.outcome for record in records] == [
        RunOutcome.ERRORED,
        RunOutcome.ERRORED,
        RunOutcome.PASSED,
    ], "each trial is a run of its own, the two that reached no verdict included"
    assert {(r.check, r.check_version, r.version) for r in records} == {
        (CHECK.name, CHECK.version, HEAD)
    }
    assert report.sha256 == digest(report.results) and harness.provider.live == set()

    bounded = Executor(tmp_path / "bounded", max_bytes=100)
    report = await bounded.executor.run(ctx, request)
    assert [r.outcome for r in collected(report, request)] == [RunOutcome.ERRORED] * 3, (
        "results past the bound a run reads are no verdict either"
    )
    assert bounded.provider.live == set()


async def test_a_record_names_what_the_executor_made_never_the_runners_start_line(
    tmp_path: Path,
) -> None:
    """The runner writes host `executor-host`, isolation `vm`, and an image
    digest in its start line; the delivered code can print any of them."""
    ctx = context(Role.OWNER, make_org())
    request = a_request()

    cloud = Executor(tmp_path / "cloud")
    (record,) = collected(await cloud.executor.run(ctx, request), request)
    assert (record.host, record.isolation, record.run_image.image) == (
        "cloud",
        IsolationMode.TWIN.value,
        "python:3.14",
    )
    assert record.run_image.toolchain == {"python": "3.14"}, "the toolchain is the runner's"

    pooled = Executor(tmp_path / "pool", pinned=True, pool=True)
    (record,) = collected(await pooled.executor.run(ctx, request), request)
    assert (record.host, record.isolation, record.run_image.image) == (
        "pool",
        IsolationMode.TWIN.value,
        "pool",
    )


async def test_a_trial_fails_unless_its_run_passes_as_its_record_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that says it passed, with every case skipped, showed nothing:
    the rate's stopping rule sees a failure."""
    harness = Executor(tmp_path)
    seen: list[list[bool]] = []

    def stops(rule: RateRule, failed: list[bool], confidence: float) -> int | None:
        seen.append(list(failed))
        return None

    async def skips_every_case(command: CommandSpec, env: Mapping[str, str]) -> TwinReply:
        workspace = harness.provider.made[-1]
        if command.argv[0] == "sh":
            return TwinReply(stdout=f"{ROOT}\n")
        out = command.argv[-1].removeprefix("--out=")
        lines = stream(
            CHECK.name, CHECK.version, HEAD, "passed", Provenance.REAL, utcnow(), ("skipped",)
        )
        written = "\n".join(json.dumps(line) for line in lines).encode()
        await harness.transport.write_file(workspace, out.removeprefix(f"{ROOT}/"), written, 1)
        return TwinReply()

    harness.transport.handler = skips_every_case
    monkeypatch.setattr(executor_module, "stops_at", stops)
    rate = RateRule(max_rate=0.1, confidence=0.9, trials=2)
    request = a_request(trials=2).model_copy(update={"rates": (rate,)})

    await harness.executor.run(context(Role.OWNER, make_org()), request)

    assert seen == [[], [True]], "the passing trial's record decides, not its last line"


def collected(report: ExecutorReport, request: ExecutionRequest) -> tuple[ExecutionRecord, ...]:
    """The records a report holds, as the evidence reads them."""
    return collect(
        report.results,
        executor=report.executor,
        agent_session_id=request.agent_session_id,
        agent_project=request.agent_project,
        purpose=request.purpose,
        validation_id=new_id(),
        now=utcnow(),
        prepared=report.prepared,
    )


# Check 2: a pinned session's checks run on an instance a host of its pool
# makes for the run, never on the cloud's, and it is destroyed whatever
# ended the run.


async def test_a_pinned_sessions_checks_run_on_an_instance_of_its_pool(tmp_path: Path) -> None:
    harness = Executor(tmp_path, pinned=True, pool=True)
    ctx = context(Role.OWNER, make_org())
    request = a_request()

    report = await harness.executor.run(ctx, request)

    assert harness.pool is not None and harness.cloud.made == [], "nothing of the cloud's"
    ((agent_session_id, instance_id, spec),) = harness.pool.asked
    assert agent_session_id == request.agent_session_id and instance_id != agent_session_id, (
        "an instance of its own, made for the session, never its workspace"
    )
    assert spec == PINNED, "to the isolation the session is pinned to, which its pool gives"
    assert report.executor == f"executor:{instance_id}"
    assert report.sha256 == digest(report.results) and report.results
    assert harness.pool.destroyed == [instance_id] and harness.provider.live == set()


async def test_a_pinned_sessions_instance_goes_whatever_ended_its_run(tmp_path: Path) -> None:
    harness = Executor(tmp_path, pinned=True, pool=True)

    harness.transport.handler = unpacks_nothing
    with pytest.raises(Unavailable, match="did not unpack"):
        await harness.executor.run(context(Role.OWNER, make_org()), a_request())

    assert harness.pool is not None
    assert [made.id for made in harness.provider.made] == harness.pool.destroyed
    assert harness.provider.live == set()


async def test_a_pinned_session_is_refused_where_no_pool_is_reached(
    tmp_path: Path,
) -> None:
    harness = Executor(tmp_path, pinned=True)

    with pytest.raises(Unavailable, match="inside its tenant's wall"):
        await harness.executor.run(context(Role.OWNER, make_org()), a_request())

    assert harness.provider.made == [] and harness.trees == []


def needs_its_workspace_base(harness: Executor) -> TwinHandler:
    """A check that imports what the workspace base's setup installed: it
    crashes on an instance that started from no base."""
    answer = harness._answer  # pyright: ignore[reportPrivateUsage]

    async def handler(command: CommandSpec, env: Mapping[str, str]) -> TwinReply:
        workspace = harness.provider.made[-1]
        if command.argv[0] != "sh" and workspace.id not in harness.provider.bases:
            return TwinReply(1, stderr="ModuleNotFoundError: No module named 'numpy'")
        return await answer(command, env)

    return handler


# Check 1: a session pinned to its agent project's workspace base has its checks run
# on a new instance of that base, with no egress, and the record names the
# base's image.


async def test_a_sessions_checks_run_on_a_new_instance_of_the_base_it_pinned(
    tmp_path: Path,
) -> None:
    harness = Executor(tmp_path, pin=ON_WORKSPACE_BASE)
    harness.transport.handler = needs_its_workspace_base(harness)
    ctx = context(Role.OWNER, make_org())
    request = a_request()

    report = await harness.executor.run(ctx, request)

    (made,) = harness.provider.made
    assert made.id != request.agent_session_id, (
        "an instance of its own, never the session's workspace"
    )
    assert made.spec.base == AGENT_WORKSPACE_BASE, "on the workspace base's image and setup"
    assert made.spec.egress == EgressPolicy(mode=EgressMode.NONE), (
        "the setup's egress is its build's alone"
    )
    assert (made.spec.mode, made.spec.limits) == (IsolationMode.TWIN, ExecutorOptions().limits), (
        "at the executor's own isolation"
    )
    assert harness.bases == [made.spec], "the base is read by what the spec names alone"
    assert harness.provider.started == [(None, WORKSPACE_BASE_SNAPSHOT)], (
        "started from the base's snapshot, never from a snapshot of the session's work"
    )
    (record,) = collected(report, request)
    assert record.outcome is RunOutcome.PASSED, "the check finds what the setup installed"
    assert (record.host, record.run_image.image) == ("cloud", AGENT_WORKSPACE_BASE.image)
    assert harness.provider.live == set(), "and the instance goes after its run"

    # A base that is its image alone needs no snapshot: the instance runs it.
    bare = Executor(
        tmp_path / "image",
        pin=ON_WORKSPACE_BASE.model_copy(
            update={"base": AgentWorkspaceBase(image=AGENT_WORKSPACE_BASE.image)}
        ),
    )
    (record,) = collected(await bare.executor.run(ctx, request), request)
    assert bare.bases == [] and bare.provider.started == [(None, None)]
    assert bare.provider.made[0].spec.base == AgentWorkspaceBase(image=AGENT_WORKSPACE_BASE.image)
    assert record.run_image.image == AGENT_WORKSPACE_BASE.image


async def test_a_base_with_setup_is_refused_where_no_base_is_read(tmp_path: Path) -> None:
    harness = Executor(tmp_path, pin=ON_WORKSPACE_BASE, bases=False)

    with pytest.raises(Unavailable, match="never run on the bare image"):
        await harness.executor.run(context(Role.OWNER, make_org()), a_request())

    assert harness.provider.made == [] and harness.trees == []


# Check 2: a session that pinned no workspace base runs as before: no base, and
# the record names the executor's own image.


async def test_a_session_with_no_workspace_base_runs_on_the_executors_own_image(
    tmp_path: Path,
) -> None:
    ctx = context(Role.OWNER, make_org())
    request = a_request()
    no_base = ON_WORKSPACE_BASE.model_copy(update={"base": None})
    for name, pin in (("never-pinned", None), ("no-base", no_base)):
        harness = Executor(tmp_path / name, pin=pin)

        (record,) = collected(await harness.executor.run(ctx, request), request)

        (made,) = harness.provider.made
        assert made.spec == IsolationSpec(
            mode=IsolationMode.TWIN, egress=EgressPolicy(mode=EgressMode.NONE)
        ), name
        assert harness.bases == [] and harness.provider.started == [(None, None)], name
        assert (record.host, record.run_image.image) == ("cloud", "python:3.14"), name


# Check 3: a session inside the wall pinned to its agent project's workspace base has
# its checks run on an instance a host of its pool makes on that base, with no
# egress, whatever egress the session holds.


async def test_a_walled_sessions_checks_run_on_the_base_it_pinned_with_no_egress(
    tmp_path: Path,
) -> None:
    opened = ON_WORKSPACE_BASE.model_copy(update={"egress": EgressPolicy(mode=EgressMode.OPEN)})
    harness = Executor(tmp_path, pinned=True, pool=True, pin=opened)
    harness.transport.handler = needs_its_workspace_base(harness)
    ctx = context(Role.OWNER, make_org())
    request = a_request()

    report = await harness.executor.run(ctx, request)

    assert harness.pool is not None and harness.cloud.made == [], "nothing of the cloud's"
    ((agent_session_id, instance_id, spec),) = harness.pool.asked
    assert agent_session_id == request.agent_session_id and instance_id != agent_session_id
    assert spec.base == AGENT_WORKSPACE_BASE, "the host makes it on the base the session pinned"
    assert spec.egress == EgressPolicy(mode=EgressMode.NONE), (
        "neither the setup's egress nor the session's reaches the checks"
    )
    assert spec == opened.model_copy(update={"egress": EgressPolicy(mode=EgressMode.NONE)}), (
        "the rest is the session's pinned isolation, which its pool gives"
    )
    assert harness.bases == [], "the host reads its own base, never the platform's"
    assert harness.provider.started == [(None, HOSTED)]
    (record,) = collected(report, request)
    assert record.outcome is RunOutcome.PASSED, "the check finds what the setup installed"
    assert (record.host, record.run_image.image) == ("pool", AGENT_WORKSPACE_BASE.image)
    assert harness.pool.destroyed == [instance_id] and harness.provider.live == set()
