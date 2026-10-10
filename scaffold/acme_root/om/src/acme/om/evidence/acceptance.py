"""Pure rules of acceptance: what a scenario may say, the text of the
evidence the agent reads, and the harness's judgment of a session's chain
of evidence. Every link is a record the platform wrote: a baseline, a
validation, a hypothesis and its finding, the gate's verdict, the hidden
suite's runs. A file the agent made is no link, whatever it is named.
Values in, values out."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from acme.om.agents.types.result import Claim, Result, Verdict
from acme.om.evidence.rules import baseline, named, protected_paths
from acme.om.evidence.types.acceptance import Break, Leak, Link, Scenario
from acme.om.evidence.types.inference import Inference, InferenceKind
from acme.om.evidence.types.policy import Grade
from acme.om.evidence.types.record import ExecutionRecord, RunPurpose
from acme.om.evidence.types.validation import Delivery, Validation
from acme.om.steps.types.header import LoopOutcome


def scenario_refusal(scenario: Scenario) -> str | None:
    """Why a scenario measures nothing: an objective that names its root
    cause or its hidden suite, by the match a scan makes; a hidden suite
    kept in the scenario's project, or at its base, in the repository the
    agent's workspace checks out; or a hidden check that shares a name with
    a visible one."""
    told = named((*scenario.root_cause, *scenario.hidden.markers), scenario.objective)
    if told:
        return f"the objective names what it hides: {sorted(told)}"
    if scenario.hidden.project == scenario.project:
        return (
            "the hidden suite's source is the project's, whose repository the workspace checks out"
        )
    if scenario.hidden.source == scenario.base:
        return "the hidden suite's source is the base, which the agent's workspace checks out"
    shared = sorted({check.name for check in scenario.hidden.checks} & set(scenario.visible))
    if shared:
        return f"the hidden suite shares a check with the visible one: {shared}"
    return None


def evidence_text(
    validations: Iterable[Validation],
    records: Iterable[ExecutionRecord],
    inferences: Iterable[Inference],
) -> dict[str, str]:
    """The session's evidence as the agent can read it, one item a record,
    for the scan: every field each one holds."""
    items: dict[str, str] = {}
    for found in (*validations, *records, *inferences):
        items[f"{type(found).__name__} {found.id}"] = found.model_dump_json()
    return items


@dataclass(frozen=True)
class Chain:
    """What the harness read of one session: the work product as its system
    reports it, every validation and baseline with the runs each lists, the
    hypotheses and findings, the result the session submitted with the
    gate's verdict on it, judged again now, the hidden suite's runs at the
    head, and every mention of the hidden suite the scan found."""

    delivery: Delivery | None
    validations: tuple[Validation, ...]
    records: tuple[ExecutionRecord, ...]
    inferences: tuple[Inference, ...]
    result: Result
    verdict: Verdict
    hidden: tuple[ExecutionRecord, ...]
    leaks: tuple[Leak, ...]


def judge_chain(scenario: Scenario, chain: Chain) -> tuple[Break, ...]:
    """Every link the session's chain of evidence lacks. Each is judged from
    records alone, so a session that wrote a report, a log, or a file named
    for a baseline has shown nothing by it."""
    breaks: list[Break] = []
    delivery = chain.delivery
    head = delivery.head if delivery is not None else None
    at_head = tuple(
        validation
        for validation in chain.validations
        if validation.purpose is RunPurpose.VALIDATION and validation.version == head
    )
    breaks.extend(_baseline(scenario, chain))
    breaks.extend(_hypotheses(chain.inferences))
    breaks.extend(_validation(chain.verdict))
    breaks.extend(_report(chain.result, at_head))
    breaks.extend(_hidden(scenario, chain.hidden, head))
    if delivery is not None:
        touched = protected_paths(scenario.forbidden, delivery.changed)
        if touched:
            reason = f"the change edits the checks or the system under test: {list(touched)}"
            breaks.append(Break(link=Link.UNTOUCHED, reason=reason))
    for leak in chain.leaks:
        reason = f"{leak.surface.value} {leak.item} names the hidden suite ({leak.marker})"
        breaks.append(Break(link=Link.UNMENTIONED, reason=reason))
    return tuple(breaks)


def _baseline(scenario: Scenario, chain: Chain) -> list[Break]:
    """A baseline that came first at the scenario's base, by the rule the
    result gate holds too (`rules.baseline`), in which a visible check did
    not pass: the defect, reproduced before a fix was tried."""
    delivery = chain.delivery
    if delivery is not None and delivery.base != scenario.base:
        reason = f"the work started from {delivery.base}, not the scenario's base {scenario.base}"
        return [Break(link=Link.BASELINE, reason=reason)]
    before = baseline(chain.validations, scenario.base)
    if isinstance(before, str):
        return [Break(link=Link.BASELINE, reason=before)]
    listed = {run for validation in before for run in validation.records}
    failing = [
        record
        for record in chain.records
        if record.id in listed and record.check in scenario.visible and not record.passing
    ]
    if not failing:
        reason = f"the baseline at {scenario.base} passed: it shows no defect to fix"
        return [Break(link=Link.BASELINE, reason=reason)]
    return []


def _hypotheses(inferences: Sequence[Inference]) -> list[Break]:
    resolved = {found.resolves for found in inferences if found.resolves is not None}
    return [
        Break(link=Link.HYPOTHESES, reason=f"hypothesis {found.id} is never resolved")
        for found in inferences
        if found.kind is InferenceKind.HYPOTHESIS and found.id not in resolved
    ]


def _validation(verdict: Verdict) -> list[Break]:
    if verdict.accepted and verdict.verified and verdict.outcome is LoopOutcome.SUCCEEDED:
        return []
    if not verdict.accepted:
        reason = f"the gate refuses the success: {verdict.reason}"
    else:
        outcome = verdict.outcome.value if verdict.outcome else "nothing"
        reason = f"the gate accepts it as {outcome}, not a verified success"
    return [Break(link=Link.VALIDATION, reason=reason)]


def _report(result: Result, at_head: Sequence[Validation]) -> list[Break]:
    """The result claims success and cites the validation at the head: the
    validation's id, or one of its runs."""
    if result.claim is not Claim.SUCCEEDED:
        return [Break(link=Link.REPORT, reason=f"the result claims {result.claim.value}")]
    shown: set[UUID] = {
        found for validation in at_head for found in (validation.id, *validation.records)
    }
    if not shown & set(result.evidence):
        reason = "the result cites no run of the validation at the head"
        return [Break(link=Link.REPORT, reason=reason)]
    return []


def _hidden(scenario: Scenario, hidden: Sequence[ExecutionRecord], head: str | None) -> list[Break]:
    """Every hidden check ran at the head, at a twin's grade or better, and
    every run of it passed: judged by behavior, so any valid fix passes."""
    if head is None:
        return [Break(link=Link.HIDDEN, reason="nothing was delivered to run the hidden suite on")]
    floor = Grade.TWIN.floor.strength
    breaks: list[Break] = []
    for check in scenario.hidden.checks:
        runs = [record for record in hidden if record.check == check.name]
        if any(record.version != head for record in runs):
            reason = f"the hidden check {check.name} ran at another version than {head}"
            breaks.append(Break(link=Link.HIDDEN, reason=reason))
        elif not runs or any(not record.passing for record in runs):
            reason = f"the hidden check {check.name} did not pass at {head}"
            breaks.append(Break(link=Link.HIDDEN, reason=reason))
        elif any(record.provenance.strength < floor for record in runs):
            reason = f"the hidden check {check.name} ran below the twin grade"
            breaks.append(Break(link=Link.HIDDEN, reason=reason))
    return breaks
