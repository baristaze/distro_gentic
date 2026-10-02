"""What the acceptance suites share: a scenario on the `arm` project, an
executor whose visible check fails at the base and passes once the change
is in, and a scripted run, the path a session takes through the evidence,
one step at a time, so each case can leave a link out."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID

from acme.om.agents.gate import ResultGateInterface
from acme.om.agents.types.result import Claim, Result
from acme.om.base import new_id, utcnow
from acme.om.benchmarks.rules import schedule
from acme.om.benchmarks.types.benchmark import Trial
from acme.om.context import TenantContext
from acme.om.evidence import EvidenceManagerInterface
from acme.om.evidence.impl.harness import AcceptanceHarnessImpl
from acme.om.evidence.impl.ports import WorkProductMemoryImpl
from acme.om.evidence.storage import EvidenceStorageInterface
from acme.om.evidence.types.acceptance import AcceptanceVerdict, HiddenSuite, Scenario, Surface
from acme.om.evidence.types.contract import CheckDeclaration
from acme.om.evidence.types.inference import Inference, InferenceKind, Stance
from acme.om.evidence.types.provenance import ArtifactRef, Provenance
from acme.om.evidence.types.record import ExecutionRecord, RunPurpose
from acme.om.evidence.types.validation import Delivery, ExecutionRequest, ExecutorReport, Validation
from contracts.evidence import Evidence, ScriptedExecutor
from contracts.evidence_storage import HASH, make_record

BASE = "base0"
HEAD = "c0ffee"

COMPLETE = CheckDeclaration(
    name="export-complete",
    version="1",
    command=("complete-suite", "{version}", "{out}"),
    kind="suite",
    schema_version=1,
)

EXPORT = Scenario(
    name="orders-vanish",
    project="arm",
    base=BASE,
    objective="Some orders never reach the nightly export. Make every one of them reach it.",
    root_cause=("page boundary",),
    visible=("unit",),
    hidden=HiddenSuite(checks=(COMPLETE,), markers=("export-complete", "hidden/complete_suite.py")),
    forbidden=("tests/**", "hidden/**", "service/**"),
)
"""The defect is a page boundary the objective never names. The project's
`unit` check shows it at the base; the hidden `export-complete` suite
judges the fix by behavior; the checks and the service under test are off
limits."""


def surfaces(**extra: Mapping[str, str]) -> dict[Surface, dict[str, str]]:
    """What the agent read, besides the objective and its evidence."""
    read = {
        Surface.PROMPT: {"kind": "You deliver the work, and submit it with its evidence."},
        Surface.KNOWLEDGE: {"export": "The export runs nightly over every order."},
        Surface.TOOL_SOURCE: {"validate": "Runs the project's checks on a fresh executor."},
        Surface.PULL_REQUEST: {"description": "Every order reaches the export again."},
    }
    for name, items in extra.items():
        read[Surface(name)] = {**read[Surface(name)], **items}
    return read


@dataclass
class DefectExecutor(ScriptedExecutor):
    """An executor over a defect: at a version in `broken` the visible check
    fails, and the hidden suite passes unless `hidden_passes` says not."""

    broken: frozenset[str] = frozenset({BASE})
    hidden_passes: bool = True

    async def run(self, ctx: TenantContext, request: ExecutionRequest) -> ExecutorReport:
        broken, hidden = request.version in self.broken, self.hidden_passes

        def outcome(check: str, trial: int) -> str:
            if check == COMPLETE.name:
                return "passed" if hidden else "failed"
            return "failed" if broken else "passed"

        self.outcome = outcome
        return await super().run(ctx, request)


@dataclass
class EvidenceParts:
    """The evidence a scripted run goes through: the manager and its
    storage, the work product the case delivers, the executor, and
    the gate."""

    manager: EvidenceManagerInterface
    storage: EvidenceStorageInterface
    work: WorkProductMemoryImpl
    executor: DefectExecutor
    gate: ResultGateInterface

    @classmethod
    def of(cls, evidence: Evidence) -> EvidenceParts:
        assert isinstance(evidence.executor, DefectExecutor)
        return cls(
            evidence.manager, evidence.storage, evidence.work, evidence.executor, evidence.gate
        )


@dataclass
class ScriptedRun:
    """One session on `EXPORT`, scripted: each step is what a session's tool
    call does to the evidence."""

    evidence: EvidenceParts
    ctx: TenantContext
    session: UUID = field(default_factory=new_id)

    @property
    def harness(self) -> AcceptanceHarnessImpl:
        return AcceptanceHarnessImpl(
            self.evidence.storage,
            self.evidence.work,
            self.evidence.executor,
            self.evidence.gate,
        )

    def deliver(self, head: str = BASE, changed: tuple[str, ...] = ()) -> None:
        delivery = Delivery(project="arm", base=BASE, head=head, changed=changed)
        self.evidence.work.deliver(self.ctx.org_id, self.session, delivery)

    async def baseline(self) -> Validation:
        return await self.evidence.manager.validate(self.ctx, self.session, RunPurpose.BASELINE)

    async def work_run(self, version: str = BASE, files: tuple[str, ...] = ()) -> ExecutionRecord:
        """A run of the agent's own, in its workspace, with the files it made
        as its artifacts."""
        record = make_record(self.session, step_id=new_id(), version=version)
        made = tuple(
            ArtifactRef(name=name, sha256=HASH, provenance=Provenance.REAL) for name in files
        )
        record = record.model_copy(update={"artifacts": (*record.artifacts, *made)})
        return await self.evidence.manager.record_run(self.ctx, record)

    async def hypothesis(self) -> Inference:
        stated = Inference(
            id=new_id(),
            created_at=utcnow(),
            session_id=self.session,
            step_id=new_id(),
            kind=InferenceKind.HYPOTHESIS,
        )
        return await self.evidence.manager.record_inference(self.ctx, stated)

    async def finding(self, hypothesis: Inference, run: ExecutionRecord) -> Inference:
        found = Inference(
            id=new_id(),
            created_at=utcnow(),
            session_id=self.session,
            step_id=new_id(),
            kind=InferenceKind.FINDING,
            resolves=hypothesis.id,
            stance=Stance.SUPPORTED,
            supports=(run.id,),
        )
        return await self.evidence.manager.record_inference(self.ctx, found)

    async def change(self, *changed: str) -> Validation:
        """Commits the change and validates the head."""
        self.deliver(HEAD, changed or ("src/export.py",))
        return await self.evidence.manager.validate(self.ctx, self.session, RunPurpose.VALIDATION)

    async def judge(self, result: Result, **extra: Mapping[str, str]) -> AcceptanceVerdict:
        return await self.harness.judge(self.ctx, EXPORT, self.session, result, surfaces(**extra))


async def whole(run: ScriptedRun, *changed: str) -> Result:
    """The whole chain: a baseline that fails at the base, a reproduction, a
    hypothesis and the finding that resolves it, the change validated at a
    clean head, and a result that cites that validation."""
    run.deliver()
    await run.baseline()
    reproduced = await run.work_run()
    stated = await run.hypothesis()
    await run.finding(stated, reproduced)
    validation = await run.change(*changed)
    return Result(claim=Claim.SUCCEEDED, evidence=(validation.id,))


async def judged_trials(parts: EvidenceParts, ctx: TenantContext, pairs: int) -> tuple[Trial, ...]:
    """Trials of both arms on one station, in the schedule's order: each a
    scripted session whose chain is whole, judged by the harness. Scripted
    sessions spend nothing, so each trial costs nothing."""
    trials: list[Trial] = []
    for arm in schedule(pairs):
        run = ScriptedRun(parts, ctx)
        verdict = await run.judge(await whole(run))
        trials.append(
            Trial(
                arm=arm,
                session_id=run.session,
                station=parts.executor.name,
                started_at=verdict.created_at,
                verdict=verdict,
                cost_micros=0,
            )
        )
    return tuple(trials)
