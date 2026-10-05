"""Validation sessions over the API, as a CI job asks for one: a member who
may write starts one for a check its project's policy declares, at a
delivered head with its checks from a base, under an Idempotency-Key, and
reads its verdict once the platform's worker has run it. A viewer starts
none; another tenant starts nothing on the project and reads nothing of the
session; a check the policy does not declare is refused before anything is
queued. A run passes only at the grade the policy asks of its check: on a
double, or with a dependency that was not there, it never does. A check
the policy rates runs its declared trials and passes only on the batch:
one trial never passes it. A session the worker refuses for good reads
refused, with its reason."""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from api_support import build_container, seed_request, sign_in_as
from contracts.evidence import ScriptedExecutor
from contracts.evidence_storage import make_policy
from tenant_support import Headers, person, refused

from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext, Role, TenantContext
from acme.om.evidence.rules import policy_key
from acme.om.evidence.types.policy import Grade, Requirement
from acme.om.evidence.types.provenance import Provenance
from acme.om.evidence.types.rate import RateRule
from acme.om.evidence.types.validation import ExecutionRequest, ExecutorReport
from acme.om.exceptions import PreconditionFailed
from acme.om.root import PlatformPorts
from acme.om.work.types.work_item import WorkKind
from acme.services.api.container import AppContainer

URL = "/v1/validation-sessions"
HEAD = "c" * 40
BASE = "b" * 40
PROJECT = {"name": "the weekly reports", "repository": {"host": "github.com", "path": "o/r"}}
LEASE = timedelta(seconds=30)
WORKER = AppContext(type=AppType.WORKER, version="worker@test")


@pytest.fixture
def executor() -> ScriptedExecutor:
    return ScriptedExecutor(capabilities=frozenset())


@pytest.fixture
def container(tmp_path: Path, executor: ScriptedExecutor) -> AppContainer:
    return build_container(tmp_path, ports=PlatformPorts(executor=executor))


@dataclass(frozen=True)
class Tenant:
    org_id: UUID
    owner: Headers
    project_id: UUID
    ctx: TenantContext


async def tenant(
    client: httpx.AsyncClient,
    container: AppContainer,
    slug: str,
    grade: Grade = Grade.TWIN,
    rate: RateRule | None = None,
) -> Tenant:
    """A tenant with its owner signed in, and a project whose policy, which
    its owner declares, holds the check `unit`, required at a twin for one
    kind of change and at `grade` (under `rate`, when set) for another."""
    email = f"owner@{slug}.test"
    ctx, org = await container.managers.tenancy.bootstrap(
        seed_request(), slug.title(), slug, email, slug.title()
    )
    owner = await sign_in_as(client, email, org.id)
    made = await client.post("/v1/projects", headers=owner, json=PROJECT)
    assert made.status_code == 201, made.text
    project_id = UUID(made.json()["id"])
    policy = make_policy(policy_key(project_id))
    graded = Requirement(check="unit", grade=grade, paths=("docs/**",), rate=rate)
    policy = policy.model_copy(update={"requirements": (*policy.requirements, graded)})
    await container.managers.evidence.write_policy(ctx, policy)
    return Tenant(org.id, owner, project_id, ctx)


def start_of(project_id: UUID, check: str = "unit", head: str = HEAD) -> dict[str, str]:
    return {"project_id": str(project_id), "check": check, "head": head, "base": BASE}


async def worker_runs(container: AppContainer) -> int:
    """The platform's worker, as it claims its own work: every validation on
    the queue run and completed. Answers how many it ran."""
    ran = 0
    while True:
        claimed = await container.managers.work.claim(
            RequestContext(request_id=new_id(), app=WORKER),
            "default",
            (WorkKind.VALIDATION,),
            "maintenance-test",
            LEASE,
        )
        if claimed is None:
            return ran
        ctx, item = claimed
        await container.managers.platform_agents.run_validation(ctx, item.target_id)
        await container.managers.work.complete(ctx, item)
        ran += 1


async def worker_refuses(container: AppContainer) -> list[str]:
    """The platform's worker, as it settles a check that cannot run: every
    validation on the queue refused, and its work failed for good. Answers
    the reasons."""
    reasons: list[str] = []
    while True:
        claimed = await container.managers.work.claim(
            RequestContext(request_id=new_id(), app=WORKER),
            "default",
            (WorkKind.VALIDATION,),
            "maintenance-test",
            LEASE,
        )
        if claimed is None:
            return reasons
        ctx, item = claimed
        with pytest.raises(PreconditionFailed) as refusal:
            await container.managers.platform_agents.run_validation(ctx, item.target_id)
        reasons.append(refusal.value.message)
        await container.managers.work.fail_for_good(ctx, item, f"refused: {reasons[-1]}")


# Check 1: a member who may write starts a validation session for a head and
# a base, under its key, and reads its verdict when it ends.


async def test_a_member_starts_a_validation_under_its_key_and_reads_its_verdict(
    client: httpx.AsyncClient, container: AppContainer, executor: ScriptedExecutor
) -> None:
    ajax = await tenant(client, container, "ajax")
    member = await person(client, container, ajax.org_id, Role.MEMBER)
    keyed = {**member, "Idempotency-Key": "ci-run-1"}

    started = await client.post(URL, headers=keyed, json=start_of(ajax.project_id))
    again = await client.post(URL, headers=keyed, json=start_of(ajax.project_id))

    assert started.status_code == 201, started.text
    session = started.json()
    assert (session["project_id"], session["check"], session["head"], session["base"]) == (
        str(ajax.project_id),
        "unit",
        HEAD,
        BASE,
    )
    assert (session["status"], session["passed"], session["run"]) == ("queued", None, None)
    assert again.status_code == 201, again.text
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["id"] == session["id"]
    assert await worker_runs(container) == 1, "one key queued one session"
    assert [(r.version, r.source) for r in executor.requests] == [(HEAD, BASE)]

    read = await client.get(f"{URL}/{session['id']}", headers=member)

    assert read.status_code == 200, read.text
    verdict = read.json()
    assert (verdict["status"], verdict["passed"], verdict["reason"]) == ("finished", True, None)
    run = verdict["run"]
    assert (run["purpose"], run["check"], run["version"], run["outcome"]) == (
        "validation",
        "unit",
        HEAD,
        "passed",
    )
    # A run that failed is a verdict that did not pass.
    executor.outcome = lambda check, trial: "failed"
    failing = await client.post(
        URL,
        headers={**member, "Idempotency-Key": "ci-run-2"},
        json=start_of(ajax.project_id, head="d" * 40),
    )
    assert failing.status_code == 201, failing.text
    assert await worker_runs(container) == 1
    failed = (await client.get(f"{URL}/{failing.json()['id']}", headers=member)).json()
    assert (failed["status"], failed["passed"], failed["reason"], failed["run"]["outcome"]) == (
        "finished",
        False,
        "unit did not pass",
        "failed",
    )


# The verdict holds the grade: a run that passed counts only when what served
# it meets the strictest grade the policy's requirements ask of its check.


@pytest.mark.parametrize(
    ("served", "grade", "reason"),
    [
        (Provenance.DOUBLE, Grade.TWIN, "the twin grade: its run's provenance is double"),
        (Provenance.UNAVAILABLE, Grade.TWIN, "the twin grade: its run's provenance is unavailable"),
        (Provenance.TWIN, Grade.REAL, "the real grade: its run's provenance is twin"),
        (Provenance.TWIN, Grade.TWIN, None),
        (Provenance.REAL, Grade.REAL, None),
    ],
)
async def test_a_passing_run_passes_only_at_the_grade_its_check_asks(
    client: httpx.AsyncClient,
    container: AppContainer,
    executor: ScriptedExecutor,
    served: Provenance,
    grade: Grade,
    reason: str | None,
) -> None:
    ajax = await tenant(client, container, "ajax", grade)
    executor.provenance = served
    started = await client.post(URL, headers=ajax.owner, json=start_of(ajax.project_id))
    assert started.status_code == 201, started.text
    assert await worker_runs(container) == 1

    read = await client.get(f"{URL}/{started.json()['id']}", headers=ajax.owner)

    assert read.status_code == 200, read.text
    verdict = read.json()
    assert (verdict["run"]["outcome"], verdict["run"]["provenance"]) == ("passed", served.value)
    assert verdict["passed"] is (reason is None)
    expected = None if reason is None else f"unit has no passing run at {reason}"
    assert verdict["reason"] == expected


# A rated check runs its declared trials, and its verdict reads them as one
# batch: a first trial that passed never passes it alone.

RATE = RateRule(max_rate=0.5, confidence=0.9, trials=5)
"""Five trials with no failure bound the rate under half; one failure does
not."""


@pytest.mark.parametrize(
    ("fails", "one_trial", "reason"),
    [
        (None, False, None),
        (2, False, "unit: "),
        (None, True, "unit ran 1 of the 5 trials declared"),
    ],
)
async def test_a_rated_check_runs_its_trials_and_never_passes_on_one(
    client: httpx.AsyncClient,
    container: AppContainer,
    executor: ScriptedExecutor,
    monkeypatch: pytest.MonkeyPatch,
    fails: int | None,
    one_trial: bool,
    reason: str | None,
) -> None:
    ajax = await tenant(client, container, "ajax", rate=RATE)
    executor.outcome = lambda check, trial: "failed" if trial == fails else "passed"
    asked: list[tuple[int, ...]] = []
    scripted = executor.run

    async def run(ctx: TenantContext, request: ExecutionRequest) -> ExecutorReport:
        # What the platform asked for, and, for `one_trial`, an executor
        # that runs one trial whatever it is asked.
        asked.append(request.trials)
        ran = request.model_copy(update={"trials": (1,)}) if one_trial else request
        return await scripted(ctx, ran)

    monkeypatch.setattr(executor, "run", run)
    started = await client.post(URL, headers=ajax.owner, json=start_of(ajax.project_id))
    assert started.status_code == 201, started.text
    assert await worker_runs(container) == 1

    read = await client.get(f"{URL}/{started.json()['id']}", headers=ajax.owner)

    assert read.status_code == 200, read.text
    verdict = read.json()
    assert asked == [(5,)], "the declared trials were asked for"
    assert verdict["run"]["outcome"] == "passed", "the last trial passed"
    assert verdict["passed"] is (reason is None)
    if reason is not None:
        assert reason in verdict["reason"]


# Check 2: a member without the write permission starts nothing, and a
# member of another tenant starts nothing on the project and reads nothing.


async def test_a_viewer_starts_none_and_another_tenant_starts_and_reads_nothing(
    client: httpx.AsyncClient, container: AppContainer, executor: ScriptedExecutor
) -> None:
    ajax = await tenant(client, container, "ajax")
    beta = await tenant(client, container, "beta")
    viewer = await person(client, container, ajax.org_id, Role.VIEWER)

    refused(
        await client.post(URL, headers=viewer, json=start_of(ajax.project_id)),
        403,
        "not_authorized",
    )
    # Ajax's project has no policy in beta's tenant: answered as a project
    # nobody holds is.
    crossed = await client.post(URL, headers=beta.owner, json=start_of(ajax.project_id))
    unknown = await client.post(URL, headers=beta.owner, json=start_of(new_id()))
    refused(crossed, 404, "not_found")
    refused(unknown, 404, "not_found")
    undeclared = await client.post(URL, headers=ajax.owner, json=start_of(ajax.project_id, "lint"))
    refused(undeclared, 422, "validation_failed")
    assert await worker_runs(container) == 0, "nothing refused was queued"
    assert executor.requests == []

    started = await client.post(URL, headers=ajax.owner, json=start_of(ajax.project_id))
    assert started.status_code == 201, started.text
    session_id = started.json()["id"]
    assert await worker_runs(container) == 1

    refused(await client.get(f"{URL}/{session_id}", headers=beta.owner), 404, "not_found")
    refused(await client.get(f"{URL}/{new_id()}", headers=beta.owner), 404, "not_found")
    # Its own tenant's verdict, the viewer reads, as it reads every record.
    seen = await client.get(f"{URL}/{session_id}", headers=viewer)
    assert (seen.status_code, seen.json()["passed"]) == (200, True)


# Check 3: a session the worker refuses for good, for a check its policy
# dropped after the start or one no executor here can run, reads refused
# with its reason, so a CI job polling it stops waiting.


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"name": "lint"}, "declares no check unit"),
        ({"capabilities": ("gpu",)}, "the check unit needs gpu, which the executor lacks"),
    ],
    ids=["dropped", "unoffered"],
)
async def test_a_session_the_worker_refuses_for_good_reads_refused_with_its_reason(
    client: httpx.AsyncClient,
    container: AppContainer,
    executor: ScriptedExecutor,
    change: dict[str, object],
    reason: str,
) -> None:
    ajax = await tenant(client, container, "ajax")
    started = await client.post(URL, headers=ajax.owner, json=start_of(ajax.project_id))
    assert started.status_code == 201, started.text
    evidence = container.managers.evidence
    policy = await evidence.get_policy(ajax.ctx, policy_key(ajax.project_id))
    checks = tuple(each.model_copy(update=change) for each in policy.checks)
    await evidence.write_policy(
        ajax.ctx, policy.model_copy(update={"checks": checks, "requirements": ()})
    )
    assert len(await worker_refuses(container)) == 1

    read = await client.get(f"{URL}/{started.json()['id']}", headers=ajax.owner)

    assert read.status_code == 200, read.text
    verdict = read.json()
    assert (verdict["status"], verdict["passed"], verdict["run"], verdict["finished_at"]) == (
        "refused",
        False,
        None,
        None,
    )
    assert reason in verdict["reason"]
    assert executor.requests == []
    assert await worker_runs(container) == 0, "nothing of it is left on the queue"
