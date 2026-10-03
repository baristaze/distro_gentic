"""What the evidence suites share: a scripted executor, which writes a
results stream as a fresh executor would, and the manager and the gate
over memory storage with a work product the case sets."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID

from acme.infra.topics.memory import TopicsMemoryImpl
from acme.om.base import utcnow
from acme.om.context import TenantContext
from acme.om.events.storage.impl.memory import EventStorageMemoryImpl
from acme.om.evidence.collector import digest
from acme.om.evidence.executor import ExecutorInterface
from acme.om.evidence.impl.gate import ResultGateEvidenceImpl
from acme.om.evidence.impl.manager import EvidenceManagerImpl, EvidenceOptions
from acme.om.evidence.impl.ports import WorkProductMemoryImpl
from acme.om.evidence.rates import stops_at
from acme.om.evidence.rules import policy_key
from acme.om.evidence.storage.impl.memory import EvidenceStorageMemoryImpl
from acme.om.evidence.types.contract import CheckDeclaration, Offer
from acme.om.evidence.types.policy import Requirement, ValidationPolicy
from acme.om.evidence.types.provenance import Provenance
from acme.om.evidence.types.validation import Delivery, ExecutionRequest, ExecutorReport
from acme.om.outbox.impl.relay import OutboxRelayImpl
from acme.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from contracts.doubles import Members, SessionProjectsMemory
from contracts.evidence_storage import make_policy

CHECKOUT = UUID("0192f3a0-0000-7000-8000-00000000a12a")
"""The `checkout` project's id: every session of a suite's evidence belongs to
it unless the suite names another."""
CHECKOUT_KEY = policy_key(CHECKOUT)
"""The key the `checkout` project's policy, and each of its validations, is kept
under."""

Outcome = Callable[[str, int], str]
"""The outcome of a check's trial, by the check's name and the trial's
number: `passed`, `failed`, `errored`, or `aborted`."""


def all_pass(check: str, trial: int) -> str:
    return "passed"


@dataclass
class ScriptedExecutor(ExecutorInterface):
    """Runs nothing: writes the results stream a fresh executor would for the
    checks it is asked, each trial's outcome as `outcome` says, every
    dependency served as `provenance` says, and each run's cases as
    `cases` says when it is set. A check with a rate stops where its rule
    stops it, as an executor does. `requests` keeps what it was asked."""

    name: str = "executor-1"
    outcome: Outcome = all_pass
    provenance: Provenance = Provenance.REAL
    capabilities: frozenset[str] = frozenset({"browser"})
    tamper: Callable[[bytes], bytes] | None = None
    cases: tuple[str, ...] | None = None
    requests: list[ExecutionRequest] = field(default_factory=list)

    async def offer(self, ctx: TenantContext) -> Offer:
        return Offer(capabilities=self.capabilities, schemas=frozenset({1}))

    async def run(self, ctx: TenantContext, request: ExecutionRequest) -> ExecutorReport:
        self.requests.append(request)
        lines: list[dict[str, Any]] = []
        start = utcnow()
        rates = request.rates or (None,) * len(request.checks)
        for check, trials, rate in zip(request.checks, request.trials, rates, strict=True):
            failed: list[bool] = []
            for trial in range(trials):
                if rate is not None and stops_at(rate, failed, rate.confidence) is not None:
                    break
                outcome = self.outcome(check.name, trial)
                failed.append(outcome != "passed")
                lines.extend(
                    stream(
                        check.name,
                        check.version,
                        request.version,
                        outcome,
                        self.provenance,
                        start,
                        self.cases,
                    )
                )
        results = "\n".join(json.dumps(line) for line in lines).encode()
        signed = digest(results)
        if self.tamper is not None:
            results = self.tamper(results)
        return ExecutorReport(executor=self.name, results=results, sha256=signed)


def stream(
    check: str,
    check_version: str,
    version: str,
    outcome: str,
    provenance: Provenance,
    at: Any,
    cases: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """One run's lines, as the contract writes them: one case that passed or
    failed with the run, or the cases named."""
    if cases is None:
        cases = ("failed" if outcome == "failed" else "passed",)
    return [
        {
            "kind": "start",
            "schema_version": 1,
            "check": check,
            "check_version": check_version,
            "version": version,
            "dirty": False,
            "environment": {"image": "sha256:" + "2" * 64, "toolchain": {"python": "3.14"}},
            "host": "executor-host",
            "isolation": "vm",
            "dependencies": [{"name": "browser", "provenance": provenance.value}],
            "started_at": at.isoformat(),
        },
        *(
            {"kind": "case", "name": f"{check}-case-{number}", "outcome": case, "seconds": 0.5}
            for number, case in enumerate(cases)
        ),
        {
            "kind": "end",
            "outcome": outcome,
            "finished_at": (at + timedelta(seconds=1)).isoformat(),
            "metrics": {"seconds": 1.0},
            **({"abort": "the guard stopped it"} if outcome == "aborted" else {}),
        },
    ]


@dataclass
class Evidence:
    manager: EvidenceManagerImpl
    gate: ResultGateEvidenceImpl
    storage: EvidenceStorageMemoryImpl
    work: WorkProductMemoryImpl
    executor: ScriptedExecutor
    members: Members
    projects: SessionProjectsMemory


def evidence_over(
    executor: ScriptedExecutor | None = None, options: EvidenceOptions | None = None
) -> Evidence:
    outbox = OutboxStorageMemoryImpl()
    storage = EvidenceStorageMemoryImpl(outbox)
    members = Members()  # pyright: ignore[reportAbstractUsage] (a partial double)
    relay = OutboxRelayImpl(outbox, EventStorageMemoryImpl(), TopicsMemoryImpl())
    work = WorkProductMemoryImpl()
    executor = executor or ScriptedExecutor()
    projects = SessionProjectsMemory(default=CHECKOUT)
    manager = EvidenceManagerImpl(
        storage, members, relay, executor, work, projects, options or EvidenceOptions()
    )
    gate = ResultGateEvidenceImpl(storage, work, projects)
    return Evidence(manager, gate, storage, work, executor, members, projects)


def checkout_policy(
    *requirements: Requirement, protected: tuple[str, ...] = ("tests/**",), project: UUID = CHECKOUT
) -> ValidationPolicy:
    """The `checkout` project's policy, kept under `project`: the `unit` check
    and the `trials` check, which needs a browser, declared; `unit` required
    for a change under `src/` unless the case names its own requirements."""
    policy = make_policy(policy_key(project))
    checks = (
        *policy.checks,
        CheckDeclaration(
            name="trials",
            version="1",
            command=("run-trials", "{version}", "{out}"),
            kind="scenario",
            capabilities=("browser",),
            schema_version=1,
        ),
    )
    return ValidationPolicy.model_validate(
        {
            **dict(policy),
            "checks": checks,
            "requirements": requirements or (Requirement(check="unit", paths=("src/**",)),),
            "protected": protected,
        }
    )


def delivered(
    head: str = "c0ffee", changed: tuple[str, ...] = ("src/cart.py",), dirty: bool = False
) -> Delivery:
    return Delivery(project="checkout", base="base0", head=head, dirty=dirty, changed=changed)
