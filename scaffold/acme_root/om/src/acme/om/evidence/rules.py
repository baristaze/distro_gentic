"""Pure rules of evidence: the key a project's policy is kept under, which
paths a policy protects, the target a tool's call reports for them, the checks a change asks for, what a
validation is asked to run, the result gate's judgment, and a validation
session's verdict. Values in, values out; no clock, no storage."""

import posixpath
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID

from acme.om.agents.rules import OUTCOMES
from acme.om.agents.types.result import Claim, Verdict
from acme.om.evidence.rates import corrected, rate_claim, stops_at
from acme.om.evidence.types.acceptance import Leak, Surface
from acme.om.evidence.types.contract import CheckDeclaration, Offer
from acme.om.evidence.types.policy import Grade, Requirement, ValidationPolicy
from acme.om.evidence.types.rate import AbortRule, Bound, RateRule
from acme.om.evidence.types.record import ExecutionRecord, RunOutcome, RunPurpose
from acme.om.evidence.types.validation import Delivery, ExecutionRequest, Validation
from acme.om.steps.types.header import LoopOutcome
from acme.om.tools.rules import DEFAULT_CEILINGS
from acme.om.tools.types.policy import Decision, PolicyLayer, PolicyRule, Target

# The policy's key.


def policy_key(project_id: UUID) -> str:
    """The key a project's validation policy is kept under: the project's
    id, as the projects answer a session's project, never a name the work
    product reports."""
    return str(project_id)


# Protected paths.

PATHS = "paths"
"""The kind of target a call that changes files reports: the paths it
changes, and whether a policy protects any of them."""

PROTECTED_CEILING = PolicyRule(
    target_kind=PATHS, target={"protected": True}, decision=Decision.DENY
)
"""The platform's ceiling: no layer lets an agent change a protected path."""

CEILINGS = PolicyLayer(rules=(*DEFAULT_CEILINGS.rules, PROTECTED_CEILING))
"""The engine's ceilings and the platform's, as a root hands them to the
tools."""


def normalized(path: str) -> str | None:
    """A path from the work product's root, as a pattern reads it: no `.`,
    no doubled or leading slash, case folded, since a file system may treat
    two cases as one file. None when it leaves the root or names nothing."""
    if not path or "\\" in path or "\x00" in path:
        return None
    folded = posixpath.normpath(path.strip().lstrip("/")).casefold()
    if folded in ("", ".") or folded == ".." or folded.startswith("../"):
        return None
    return folded


def matches(pattern: str, path: str) -> bool:
    """Whether a pattern matches a normalized path: `*` within one part,
    `**` across parts. A pattern that names a folder, with or without its
    trailing `/`, matches everything in it, as it matches a path in a folder
    it matches; a pattern of a folder's contents matches the folder too."""
    folded = pattern.strip().strip("/").casefold() or "**"
    parts = PurePosixPath(path).parts
    for depth in range(1, len(parts) + 1):
        if PurePosixPath(*parts[:depth]).full_match(folded):
            return True
    return folded.endswith("/**") and path == folded[: -len("/**")]


def protected_paths(patterns: Iterable[str], paths: Iterable[str]) -> tuple[str, ...]:
    """The paths a protected pattern matches, as given. A path that cannot be
    read from the root, such as one that climbs out of it, is counted
    protected: a path nobody can place is never let through."""
    patterns = tuple(patterns)
    found: list[str] = []
    for path in paths:
        clean = normalized(path)
        if clean is None or any(matches(pattern, clean) for pattern in patterns):
            found.append(path)
    return tuple(sorted(set(found)))


def protection_target(policy: ValidationPolicy | None, paths: Iterable[str]) -> Target:
    """What a call that changes `paths` acts on, read from the project's
    policy and never from what the call claims: whether any of them is
    protected. A project with no policy protects nothing."""
    touched = protected_paths(policy.protected if policy else (), paths)
    return Target(kind=PATHS, attributes={"protected": bool(touched)})


# What a change asks for.


def required(policy: ValidationPolicy, changed: Iterable[str]) -> tuple[Requirement, ...]:
    """The requirements a change asks for: each one a changed path of which
    matches one of its patterns. A change of nothing asks for nothing."""
    paths = [clean for path in changed if (clean := normalized(path)) is not None]
    return tuple(
        requirement
        for requirement in policy.requirements
        if any(matches(pattern, path) for pattern in requirement.paths for path in paths)
    )


def compatibility_refusal(check: CheckDeclaration, offer: Offer) -> str | None:
    """Why a place cannot run a check, before anything is leased for it: a
    capability it lacks, or a results schema its runner does not write."""
    missing = sorted(set(check.capabilities) - offer.capabilities)
    if missing:
        return f"the check {check.name} needs {', '.join(missing)}, which the executor lacks"
    if check.schema_version not in offer.schemas:
        return (
            f"the check {check.name} writes results schema {check.schema_version}, "
            "which the executor's runner does not"
        )
    return None


def trials_of(requirements: Iterable[Requirement]) -> dict[str, int]:
    """Each check's count of trials: the most any requirement of it declares,
    and one where none declares a rate."""
    counts: dict[str, int] = {}
    for requirement in requirements:
        count = requirement.rate.trials if requirement.rate else 1
        counts[requirement.check] = max(counts.get(requirement.check, 1), count)
    return counts


def stopping_rules(requirements: Sequence[Requirement]) -> dict[str, RateRule]:
    """The rule each rated check's trials stop by, as the executor runs them
    and the gate judges them: the rate of the requirement that declares the
    most trials, at the confidence corrected for every rate judged together."""
    rated = sum(1 for requirement in requirements if requirement.rate is not None)
    rules: dict[str, RateRule] = {}
    for requirement in requirements:
        rule = requirement.rate
        held = rules.get(requirement.check)
        if rule is not None and (held is None or rule.trials > held.trials):
            confidence = corrected(rule.confidence, rated)
            rules[requirement.check] = rule.model_copy(update={"confidence": confidence})
    return rules


def execution_request(
    session_id: UUID,
    policy: ValidationPolicy,
    delivery: Delivery,
    purpose: RunPurpose,
) -> ExecutionRequest | str:
    """What a fresh executor is asked to run, or why nothing is run. A
    validation runs the checks the change asks for at the committed head; a
    baseline runs every check the policy requires at the base version. Both
    take their checks, fixtures, and runner from the base, which the agent
    never changed. A validation is refused on a dirty tree, and on a change
    that touches a protected path, since that change voids it."""
    if purpose is RunPurpose.VALIDATION:
        if delivery.dirty:
            return (
                "the tree holds work your branch does not: commit it, open your pull request "
                "so the head is on your branch, then ask again"
            )
        touched = protected_paths(policy.protected, delivery.changed)
        if touched:
            return f"the change touches protected paths, which voids validation: {list(touched)}"
        needed = required(policy, delivery.changed) if delivery.changes_work_product else ()
        version = delivery.head
    else:
        needed = policy.requirements
        version = delivery.base
    if not needed:
        return "the policy asks for no check of this change: there is nothing to validate"
    counts = trials_of(needed)
    rules = stopping_rules(needed)
    checks = tuple(policy.declared(name) for name in sorted(counts))
    return ExecutionRequest(
        session_id=session_id,
        project=policy.project,
        purpose=purpose,
        version=version,
        source=delivery.base,
        checks=checks,
        trials=tuple(counts[check.name] for check in checks),
        rates=tuple(rules.get(check.name) for check in checks),
        protected=policy.protected,
    )


def by_environment(request: ExecutionRequest) -> dict[str, ExecutionRequest]:
    """The request as one request per environment its checks name, in name
    order: each holds that environment's checks with their own trials and
    rates, so all of a check's runs are one validation's, and the gate
    reads their batches and provenance per validation as it always does."""
    rates = request.rates or (None,) * len(request.checks)
    parts: dict[str, list[int]] = {}
    for at, check in enumerate(request.checks):
        parts.setdefault(check.environment, []).append(at)
    return {
        environment: request.model_copy(
            update={
                "checks": tuple(request.checks[at] for at in held),
                "trials": tuple(request.trials[at] for at in held),
                "rates": tuple(rates[at] for at in held) if request.rates else (),
            }
        )
        for environment, held in sorted(parts.items())
    }


# The result gate.


@dataclass(frozen=True)
class Reading:
    """What the gate read for one result: the runs its evidence names, the
    work product as its system reports it (or what could not be read),
    the project's policy, and every validation of the session at the
    delivered head with every run each one lists."""

    cited: tuple[ExecutionRecord, ...] = ()
    unresolved: tuple[UUID, ...] = ()
    delivery: Delivery | None = None
    unread: str | None = None
    policy: ValidationPolicy | None = None
    validations: tuple[Validation, ...] = ()
    records: tuple[ExecutionRecord, ...] = ()


def refused(reason: str) -> Verdict:
    return Verdict(accepted=False, reason=reason)


def accepted(outcome: LoopOutcome) -> Verdict:
    return Verdict(accepted=True, verified=True, outcome=outcome)


def judge(claim: Claim, reading: Reading) -> Verdict:
    """The result gate. A claim cites runs of its own session, each one
    found. A failure explained by runs is a result. A success that changed
    the work product counts only when the policy passed at the committed
    head, on a clean tree, on runs the validation's executor wrote, with no
    protected path touched. A success that validated nothing, because
    nothing changed or the policy asks for no check of the change, is
    inconclusive."""
    if reading.unresolved:
        names = ", ".join(str(found) for found in reading.unresolved)
        return refused(f"the evidence names no run of this session: {names}")
    if not reading.cited:
        return refused("a claim cites the runs behind it, and this one cites none")
    if claim is Claim.FAILED:
        return accepted(OUTCOMES[claim])
    if reading.unread is not None:
        return refused(
            f"the gate cannot read what it judges, so no success counts: {reading.unread}"
        )
    delivery = reading.delivery
    if delivery is None or not delivery.changes_work_product:
        return accepted(LoopOutcome.INCONCLUSIVE)
    if delivery.dirty:
        return refused(
            "the tree holds uncommitted changes: a success is judged at a committed head, "
            "on a clean tree"
        )
    policy = reading.policy
    if policy is None:
        return refused("the session's project declares no validation policy")
    touched = protected_paths(policy.protected, delivery.changed)
    if touched:
        return refused(
            f"the change touches protected paths, which voids validation: {list(touched)}. "
            "Take those changes back"
        )
    needed = required(policy, delivery.changed)
    if not needed:
        return accepted(LoopOutcome.INCONCLUSIVE)
    if not reading.validations:
        return refused(
            f"no validation ran at the head {delivery.head}: ask for one, then submit again"
        )
    unwritten = provenance_refusal(reading.validations, reading.records, delivery.head)
    if unwritten is not None:
        return refused(unwritten)
    order = {run: at for found in reading.validations for at, run in enumerate(found.records)}
    unmet = unmet_requirements(needed, reading.records, delivery.head, order)
    if unmet:
        return refused(f"the validation at {delivery.head} did not pass: " + "; ".join(unmet))
    return accepted(LoopOutcome.SUCCEEDED)


def provenance_refusal(
    validations: Sequence[Validation], records: Sequence[ExecutionRecord], head: str
) -> str | None:
    """Why the runs are not the validations' own: each validation ran at the
    head, and its runs are exactly the ones it lists, each written by its
    executor at that head from a clean tree."""
    by_validation: dict[UUID | None, list[ExecutionRecord]] = {}
    for record in records:
        by_validation.setdefault(record.validation_id, []).append(record)
    for validation in validations:
        if validation.purpose is not RunPurpose.VALIDATION or validation.version != head:
            return f"validation {validation.id} did not run at the head {head}"
        own = by_validation.get(validation.id, [])
        if {record.id for record in own} != set(validation.records):
            return f"validation {validation.id} lists runs other than the ones stored with it"
        for record in own:
            if (
                record.executor != validation.executor
                or record.purpose is not RunPurpose.VALIDATION
                or record.version != head
                or record.dirty
            ):
                return f"run {record.id} is not a result its validation's executor wrote at {head}"
    listed = {run for validation in validations for run in validation.records}
    strays = sorted(str(record.id) for record in records if record.id not in listed)
    if strays:
        return f"runs no validation lists: {strays}"
    return None


def unmet_requirements(
    needed: Sequence[Requirement],
    records: Sequence[ExecutionRecord],
    head: str,
    order: Mapping[UUID, int] | None = None,
) -> list[str]:
    """What the runs at the head leave unmet. A plain requirement needs a
    passing run at its grade and no run of its check that did not pass: a
    check run again until it passes still counts every run. A rate
    requirement judges each validation's trials as one batch, at its grade
    and its declared count, and needs every batch's bound under the declared
    rate: a batch that failed still counts after a later one passes, so
    validating again until the bound holds never passes. Its confidence is
    corrected for the number of rates judged together. A batch is read in
    the order its validation lists its runs (`order`), which is the order
    they ran. A double's run is below every grade, and a run that passed no
    case does not pass."""
    unmet: list[str] = []
    rated = sum(1 for requirement in needed if requirement.rate is not None)
    for requirement in needed:
        runs = [record for record in records if record.check == requirement.check]
        floor = requirement.grade.floor.strength
        name = requirement.check
        if requirement.rate is None:
            bad = [record for record in runs if not record.passing]
            graded = [record for record in runs if record.provenance.strength >= floor]
            if bad:
                unmet.append(f"{name} did not pass in {len(bad)} of {len(runs)} runs")
            elif not graded:
                unmet.append(f"{name} has no passing run at the {requirement.grade.value} grade")
            continue
        rule = requirement.rate
        batches: dict[UUID | None, list[ExecutionRecord]] = {}
        ran = sorted(runs, key=lambda record: (order or {}).get(record.id, len(runs)))
        for record in ran:
            batches.setdefault(record.validation_id, []).append(record)
        if not batches:
            unmet.append(f"{name} ran 0 of the {rule.trials} trials declared")
        confidence = corrected(rule.confidence, rated)
        for batch in batches.values():
            unmet.extend(batch_refusal(name, head, batch, rule, floor, confidence))
    return unmet


def batch_refusal(
    name: str,
    head: str,
    batch: Sequence[ExecutionRecord],
    rule: RateRule,
    floor: int,
    confidence: float,
) -> list[str]:
    """Why one validation's trials of a check, in the order they ran, leave
    its rate unmet: trials below the grade, fewer trials than a fixed count
    declared, a sequential test stopped anywhere but where its rule stops
    it, an abort the rule leaves without a conclusion, or a bound above
    the declared rate."""
    below = sum(1 for record in batch if record.provenance.strength < floor)
    if below:
        return [f"{name} ran {below} trials below the grade"]
    if rule.bound is Bound.SEQUENTIAL:
        stop = stops_at(rule, [not record.passing for record in batch], confidence)
        if stop is None:
            return [f"{name} ran {len(batch)} trials, and its sequential test had not stopped"]
        if stop < len(batch):
            return [
                f"{name} ran {len(batch)} trials, on past trial {stop}, "
                "where its sequential test stopped"
            ]
    elif len(batch) < rule.trials:
        return [f"{name} ran {len(batch)} of the {rule.trials} trials declared"]
    aborted = sum(1 for record in batch if record.outcome is RunOutcome.ABORTED)
    if aborted and rule.aborted is AbortRule.INCONCLUSIVE:
        return [f"{name} had {aborted} trials an abort ended"]
    claim = rate_claim(name, head, batch, confidence, rule.bound, rule.alternative)
    if claim.upper > rule.max_rate:
        return [f"{name}: {claim.render()}, above the {rule.max_rate:.2%} declared"]
    return []


# A validation session's verdict.


def check_grade(policy: ValidationPolicy, check: str) -> Grade:
    """The grade a run of `check` passes at: the strictest grade among the
    policy's requirements that name it, and a twin when none does."""
    grades = [requirement.grade for requirement in policy.requirements if requirement.check == check]
    return max(grades, key=lambda grade: grade.floor.strength, default=Grade.TWIN)


def run_refusal(record: ExecutionRecord, grade: Grade) -> str | None:
    """Why one run does not pass at `grade`, the way the result gate reads a
    plain requirement: it did not pass, or what served it is below the
    grade. A double's run, or one whose dependency was not there, passes at
    no grade."""
    if not record.passing:
        return f"{record.check} did not pass"
    if record.provenance.strength < grade.floor.strength:
        return (
            f"{record.check} has no passing run at the {grade.value} grade: "
            f"its run's provenance is {record.provenance.value}"
        )
    return None


# Acceptance: the hidden suite.


SEPARATORS = re.compile(r"[^0-9a-z]+")


def folded(text: str) -> str:
    """Text as a scan reads it: case folded, and every run of what is not a
    letter or a digit one space, so `hidden_suite`, `Hidden-Suite`, and
    `hidden suite` read alike."""
    return SEPARATORS.sub(" ", text.casefold()).strip()


def scan(
    markers: Collection[str], surfaces: Mapping[Surface, Mapping[str, str]]
) -> tuple[Leak, ...]:
    """Every mention of the hidden suite in what the agent reads: each
    surface's items, by name, against each marker of the suite (its name,
    its paths, its case names). A scan covers every surface: one left out
    is refused, never read as clean, and so is a marker too short to mean
    anything."""
    missing = sorted(set(Surface) - set(surfaces))
    if missing:
        raise ValueError(f"a scan covers every surface; missing: {[s.value for s in missing]}")
    folded_markers = {marker: folded(marker) for marker in markers}
    short = sorted(marker for marker, text in folded_markers.items() if len(text) < 3)
    if not folded_markers or short:
        raise ValueError(f"a scan names the hidden suite by markers of three characters: {short}")
    leaks: list[Leak] = []
    for surface in Surface:
        for item, text in surfaces[surface].items():
            for marker in _named(folded_markers, text):
                leaks.append(Leak(surface=surface, item=item, marker=marker))
    return tuple(leaks)


def named(markers: Collection[str], text: str) -> tuple[str, ...]:
    """The markers `text` names, as a scan reads both: folded, and each
    marker found anywhere in the text, inside a longer word too."""
    return _named({marker: folded(marker) for marker in markers}, text)


def _named(needles: Mapping[str, str], text: str) -> tuple[str, ...]:
    """The markers whose folded form (`needles`) the folded `text` holds:
    the one match `scan` and `named` make."""
    haystack = folded(text)
    return tuple(marker for marker, needle in needles.items() if needle in haystack)
