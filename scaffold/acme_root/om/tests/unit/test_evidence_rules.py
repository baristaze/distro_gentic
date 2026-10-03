"""The pure rules of evidence: protected paths, what a change asks for, the
results contract and its one collector, and the acceptance scanner."""

import json
from typing import Any

import pytest
from contracts.evidence import arm_policy, delivered, stream
from contracts.evidence_storage import make_policy

from acme.om.base import new_id, utcnow
from acme.om.evidence.collector import Collector, collect
from acme.om.evidence.rules import (
    compatibility_refusal,
    execution_request,
    protected_paths,
    protection_target,
    required,
    scan,
)
from acme.om.evidence.types.acceptance import Surface
from acme.om.evidence.types.contract import CheckDeclaration, Offer
from acme.om.evidence.types.policy import Requirement, ValidationPolicy
from acme.om.evidence.types.provenance import Provenance
from acme.om.evidence.types.record import RunOutcome, RunPurpose
from acme.om.evidence.types.validation import ExecutionRequest
from acme.om.exceptions import ValidationFailed

# Protected paths.

PATTERNS = ("tests/**", "**/conftest.py", "pytest.ini", ".github/workflows/*")


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_grip.py",
        "tests/fixtures/arm.json",
        "src/arm/conftest.py",
        "conftest.py",
        "pytest.ini",
        ".github/workflows/ci.yml",
        "./tests/test_grip.py",
        "/tests/test_grip.py",
        "Tests/Test_Grip.py",
        "src/../tests/test_grip.py",
        "tests",
        "../outside.py",
        "",
    ],
)
def test_a_protected_path_is_found_however_it_is_spelled(path: str) -> None:
    assert protected_paths(PATTERNS, [path]) == (path,)


@pytest.mark.parametrize(
    "path", ["src/grip.py", "docs/tests.md", "src/tests_helper.py", ".github/dependabot.yml"]
)
def test_a_path_no_pattern_matches_is_free(path: str) -> None:
    assert protected_paths(PATTERNS, [path]) == ()


@pytest.mark.parametrize("pattern", ["tests/", "tests", "/tests/", "Tests/", "tests/**"])
def test_a_pattern_that_names_a_folder_protects_everything_in_it(pattern: str) -> None:
    paths = ["tests/test_x.py", "tests/fixtures/arm.json", "tests"]
    assert protected_paths([pattern], paths) == tuple(sorted(paths))
    assert protected_paths([pattern], ["src/tests.py", "docs/tests/a.md"]) == ()


def test_a_glob_that_names_folders_protects_what_they_hold() -> None:
    assert protected_paths(["src/*/fixtures"], ["src/arm/fixtures/a.json"]) == (
        "src/arm/fixtures/a.json",
    )
    assert protected_paths(["src/*/fixtures/"], ["src/arm/main.py"]) == ()


def test_the_target_is_read_from_the_policy_never_from_the_call() -> None:
    policy = arm_policy(protected=PATTERNS)
    assert protection_target(policy, ["src/grip.py", "tests/a.py"]).attributes == {
        "protected": True
    }
    assert protection_target(policy, ["src/grip.py"]).attributes == {"protected": False}
    assert protection_target(None, ["tests/a.py"]).attributes == {"protected": False}
    assert protection_target(policy, []).kind == "paths"


# What a change asks for.


def test_a_change_asks_for_the_checks_whose_paths_it_touches() -> None:
    policy = arm_policy(
        Requirement(check="unit", paths=("src/**",)),
        Requirement(check="trials", paths=("src/arm/**", "firmware/**")),
    )
    assert [r.check for r in required(policy, ["src/grip.py"])] == ["unit"]
    assert [r.check for r in required(policy, ["src/arm/joint.py"])] == ["unit", "trials"]
    assert required(policy, ["docs/a.md"]) == ()
    assert required(policy, []) == ()


def test_a_validation_takes_its_checks_from_the_base_and_runs_at_the_head() -> None:
    policy = arm_policy()
    offer = Offer(capabilities=frozenset({"arm"}), schemas=frozenset({1}))
    request = execution_request(new_id(), policy, delivered(), RunPurpose.VALIDATION, offer)
    assert isinstance(request, ExecutionRequest)
    assert (request.version, request.source) == ("c0ffee", "base0")
    baseline = execution_request(new_id(), policy, delivered(), RunPurpose.BASELINE, offer)
    assert isinstance(baseline, ExecutionRequest)
    assert (baseline.version, baseline.source) == ("base0", "base0")


def test_a_check_the_executor_cannot_run_is_refused_before_anything_runs() -> None:
    check = CheckDeclaration(
        name="trials",
        version="1",
        command=("x", "{out}"),
        kind="scenario",
        capabilities=("arm",),
        schema_version=1,
    )
    assert compatibility_refusal(check, Offer(capabilities=frozenset(), schemas=frozenset({1})))
    assert compatibility_refusal(check, Offer(capabilities=frozenset({"arm"}), schemas=frozenset()))
    assert (
        compatibility_refusal(check, Offer(capabilities=frozenset({"arm"}), schemas=frozenset({1})))
        is None
    )
    policy = arm_policy(Requirement(check="trials", paths=("src/**",)))
    refusal = execution_request(
        new_id(),
        policy,
        delivered(),
        RunPurpose.VALIDATION,
        Offer(schemas=frozenset({1})),
    )
    assert isinstance(refusal, str) and "needs arm" in refusal


def test_a_policy_is_well_formed() -> None:
    policy = make_policy()
    fields: dict[str, Any] = policy.model_dump()
    with pytest.raises(ValueError, match="does not declare"):
        ValidationPolicy.model_validate({**fields, "requirements": [{"check": "lint"}]})
    with pytest.raises(ValueError, match="declared once"):
        ValidationPolicy.model_validate(
            {**fields, "checks": [*fields["checks"], fields["checks"][0]]}
        )
    with pytest.raises(ValueError, match="no collector reads"):
        unread = {**fields["checks"][0], "schema_version": 2}
        ValidationPolicy.model_validate({**fields, "checks": [unread]})
    with pytest.raises(ValueError):
        ValidationPolicy.model_validate(
            {**fields, "requirements": [{"check": "unit", "grade": "double"}]}
        )


# The results contract and its one collector.


def results(*runs: list[dict[str, Any]]) -> bytes:
    return "\n".join(json.dumps(line) for run in runs for line in run).encode()


def collected(data: bytes) -> Any:
    return collect(
        data,
        executor="executor-1",
        session_id=new_id(),
        project="arm",
        purpose=RunPurpose.VALIDATION,
        validation_id=new_id(),
        now=utcnow(),
    )


def test_the_collector_reads_each_run_and_streams_its_cases() -> None:
    at = utcnow()
    data = results(
        stream("unit", "1", "c0ffee", "passed", Provenance.TWIN, at),
        stream("unit", "1", "c0ffee", "failed", Provenance.REAL, at),
    )
    first, second = collected(data)
    assert first.provenance is Provenance.TWIN and first.outcome is RunOutcome.PASSED
    assert second.outcome is RunOutcome.FAILED and second.cases.failed == 1
    assert first.executor == "executor-1" and first.environment.toolchain == {"python": "3.14"}
    collector = Collector(
        executor="executor-1",
        session_id=new_id(),
        project="arm",
        purpose=RunPurpose.VALIDATION,
        validation_id=new_id(),
        now=at,
    )
    seen = [collector.feed(line) for line in data.splitlines()]
    assert [case.name for case in seen if case is not None] == ["unit-case-0", "unit-case-0"]


def a_run(**changes: Any) -> list[dict[str, Any]]:
    start, case, end = stream("unit", "1", "c0ffee", "passed", Provenance.REAL, utcnow())
    return [{**start, **changes.get("start", {})}, case, {**end, **changes.get("end", {})}]


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (b"not json", "JSONDecodeError"),
        (results(a_run(start={"schema_version": 2})), "results schema 2"),
        (results(a_run(start={"surprise": 1})), "Extra inputs"),
        (results(a_run(start={"dirty": "no"})), "dirty"),
        (results(a_run(end={"outcome": "maybe"})), "outcome"),
        (results(a_run()[:2]), "still open"),
        (results(a_run()[1:]), "outside a run"),
        (results([a_run()[0], *a_run()]), "before the last one ended"),
        (results(a_run(end={"outcome": "aborted"})), "names its abort"),
        (results(a_run(start={"dirty": True})), "never a dirty tree"),
    ],
)
def test_a_results_stream_the_contract_does_not_hold_is_refused_whole(
    data: bytes, why: str
) -> None:
    with pytest.raises(ValidationFailed, match=why):
        collected(data)


# Acceptance: the scanner.

MARKERS = ("hidden_grip_suite", "tests/hidden/test_drop.py", "test_drop_at_placement")


def clean() -> dict[Surface, dict[str, str]]:
    return {
        Surface.PROMPT: {"system": "Investigate why the export drops the record."},
        Surface.KNOWLEDGE: {"lab": "The arm's gripper needs calibration weekly."},
        Surface.TOOL_SOURCE: {"run_tests": "def run(): subprocess.run(['pytest', 'tests'])"},
        Surface.EVIDENCE: {"run-1": "unit passed 41 of 41 cases"},
        Surface.PULL_REQUEST: {"body": "Tighten the grip before the move."},
    }


def test_a_clean_set_of_surfaces_holds_no_leak() -> None:
    assert scan(MARKERS, clean()) == ()


@pytest.mark.parametrize("surface", list(Surface))
@pytest.mark.parametrize(
    "mention",
    [
        "see the hidden_grip_suite for details",
        "the Hidden-Grip-Suite checks it",
        "run tests/hidden/test_drop.py first",
        "TEST_DROP_AT_PLACEMENT fails sometimes",
    ],
)
def test_a_planted_mention_is_found_in_every_surface(surface: Surface, mention: str) -> None:
    surfaces = clean()
    surfaces[surface] = {**surfaces[surface], "planted": f"Note: {mention}."}
    leaks = scan(MARKERS, surfaces)
    assert leaks and {(leak.surface, leak.item) for leak in leaks} == {(surface, "planted")}


def test_a_scan_that_skips_a_surface_is_refused() -> None:
    surfaces = clean()
    del surfaces[Surface.PULL_REQUEST]
    with pytest.raises(ValueError, match="pull_request"):
        scan(MARKERS, surfaces)
    with pytest.raises(ValueError, match="three characters"):
        scan(("x",), clean())
    with pytest.raises(ValueError, match="three characters"):
        scan((), clean())
