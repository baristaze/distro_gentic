"""The evidence manager: a policy a person declares, the agent's runs and
its hypotheses and findings, written once, and validation on a fresh
executor that keeps only what the executor wrote and hashed."""

from collections.abc import Callable

import pytest
from contracts.doubles import context
from contracts.evidence import CHECKOUT, ScriptedExecutor, checkout_policy, delivered, evidence_over
from contracts.evidence_storage import make_finding, make_hypothesis, make_record
from contracts.factories import make_org
from pydantic import ValidationError

from acme.om.base import new_id
from acme.om.context import Role, TenantContext
from acme.om.evidence.impl.manager import EvidenceManagerImpl, EvidenceOptions
from acme.om.evidence.impl.ports import ExecutorAbsentImpl, WorkProductAbsentImpl
from acme.om.evidence.rules import policy_key
from acme.om.evidence.types.inference import Inference
from acme.om.evidence.types.policy import Requirement, ValidationPolicy
from acme.om.evidence.types.record import RunPurpose
from acme.om.evidence.types.validation import ExecutionRequest, ExecutorReport
from acme.om.exceptions import (
    NotAuthorized,
    NotFound,
    PreconditionFailed,
    Unavailable,
    ValidationFailed,
)


async def test_a_person_who_manages_the_tenant_declares_the_policy() -> None:
    org = make_org()
    evidence = evidence_over()
    owner = context(Role.OWNER, org)
    with pytest.raises(NotFound):
        await evidence.manager.get_policy(owner, policy_key(CHECKOUT))
    created = await evidence.manager.write_policy(owner, checkout_policy())
    assert created.version == 1 and created.created_by == owner.user_id
    for role in (Role.SERVICE, Role.MEMBER, Role.VIEWER):
        with pytest.raises(NotAuthorized):
            await evidence.manager.write_policy(context(role, org), created)
    moved = await evidence.manager.write_policy(
        owner, created.model_copy(update={"protected": ("**",)})
    )
    assert moved.version == 2 and moved.protected == ("**",) and moved.id == created.id
    with pytest.raises(PreconditionFailed):
        await evidence.manager.write_policy(owner, created)
    assert (
        await evidence.manager.get_policy(context(Role.VIEWER, org), policy_key(CHECKOUT)) == moved
    )


@pytest.mark.parametrize(
    "command",
    [
        ("run-trials", "{version", "{out}"),  # does not parse
        ("run-trials", "}", "{out}"),
        ("run-trials", "{ref}", "{out}"),  # a field other than the two
        ("run-trials", "{}", "{out}"),
        ("run-trials", "{out.parent}"),
        ("run-trials", "{out!r}"),  # a field, but not bare
        ("run-trials", "{out:>40}"),
        ("run-trials", "{version}"),  # no `out`
    ],
)
async def test_a_command_template_a_runner_cannot_fill_is_refused_when_written(
    command: tuple[str, ...],
) -> None:
    org = make_org()
    evidence = evidence_over()
    owner = context(Role.OWNER, org)
    declared = checkout_policy().model_dump()
    declared["checks"][-1]["command"] = list(command)
    with pytest.raises(ValidationError, match="command"):
        await evidence.manager.write_policy(owner, ValidationPolicy.model_validate(declared))
    with pytest.raises(NotFound):
        await evidence.manager.get_policy(owner, policy_key(CHECKOUT))
    declared["checks"][-1]["command"] = ["run-trials", "--at={version}", "{out}", "{{literal}}"]
    assert await evidence.manager.write_policy(owner, ValidationPolicy.model_validate(declared))


async def test_the_agents_run_is_kept_and_an_executors_is_refused_here() -> None:
    org = make_org()
    evidence = evidence_over()
    ctx = context(Role.MEMBER, org)
    session = new_id()
    run = make_record(session)
    assert await evidence.manager.record_run(ctx, run) == run
    assert await evidence.manager.record_run(ctx, run) == run, "a retry writes nothing more"
    page = await evidence.manager.get_runs(ctx, session, None, 10)
    assert page.items == (run,) and not page.has_more
    forged = make_record(session, purpose=RunPurpose.VALIDATION, validation_id=new_id())
    with pytest.raises(ValidationFailed, match="only the executor"):
        await evidence.manager.record_run(ctx, forged)


async def test_a_finding_cites_runs_of_its_session_and_resolves_its_hypothesis() -> None:
    org = make_org()
    evidence = evidence_over()
    ctx = context(Role.MEMBER, org)
    session = new_id()
    run = make_record(session)
    await evidence.manager.record_run(ctx, run)
    hypothesis = await evidence.manager.record_inference(ctx, make_hypothesis(session))
    finding = await evidence.manager.record_inference(
        ctx, make_finding(session, hypothesis.id, run.id)
    )
    page = await evidence.manager.get_inferences(ctx, session, None, 10)
    assert page.items == (hypothesis, finding)
    with pytest.raises(ValidationFailed, match="does not hold"):
        await evidence.manager.record_inference(ctx, make_finding(session, hypothesis.id, new_id()))
    other = make_record(new_id())
    await evidence.manager.record_run(ctx, other)
    with pytest.raises(ValidationFailed, match="does not hold"):
        await evidence.manager.record_inference(ctx, make_finding(session, hypothesis.id, other.id))
    with pytest.raises(ValidationFailed, match="no hypothesis"):
        await evidence.manager.record_inference(ctx, make_finding(session, finding.id, run.id))
    with pytest.raises(ValueError, match="cites the runs"):
        Inference.model_validate({**finding.model_dump(), "supports": []})


async def test_validation_keeps_what_the_executor_wrote_at_the_head() -> None:
    org = make_org()
    evidence = evidence_over()
    ctx = context(Role.MEMBER, org)
    session = new_id()
    await evidence.manager.write_policy(context(Role.OWNER, org), checkout_policy())
    evidence.work.deliver(org.id, session, delivered())
    validation = await evidence.manager.validate(ctx, session, RunPurpose.VALIDATION)
    assert (validation.version, validation.source, validation.executor) == (
        "c0ffee",
        "base0",
        "executor-1",
    )
    runs = (await evidence.manager.get_runs(ctx, session, None, 10)).items
    assert {run.id for run in runs} == set(validation.records)
    assert all(run.executor == "executor-1" and run.validation_id == validation.id for run in runs)
    assert await evidence.manager.get_validations(ctx, session, 10) == (validation,)


async def test_a_baseline_runs_every_required_check_at_the_base() -> None:
    org = make_org()
    evidence = evidence_over()
    ctx = context(Role.MEMBER, org)
    session = new_id()
    policy = checkout_policy(
        Requirement(check="unit", paths=("src/**",)),
        Requirement(check="trials", paths=("migrations/**",)),
    )
    await evidence.manager.write_policy(context(Role.OWNER, org), policy)
    evidence.work.deliver(org.id, session, delivered(head="base0", changed=()))
    baseline = await evidence.manager.validate(ctx, session, RunPurpose.BASELINE)
    assert baseline.version == "base0" and baseline.purpose is RunPurpose.BASELINE
    (request,) = evidence.executor.requests
    assert [check.name for check in request.checks] == ["trials", "unit"]


@pytest.mark.parametrize(
    "tamper",
    [lambda data: data + b"\n", lambda data: data.replace(b'"failed"', b'"passed"')],
)
async def test_results_that_do_not_hash_to_what_the_executor_wrote_keep_nothing(
    tamper: Callable[[bytes], bytes],
) -> None:
    executor = ScriptedExecutor(outcome=lambda check, trial: "failed", tamper=tamper)
    org = make_org()
    evidence = evidence_over(executor)
    ctx = context(Role.MEMBER, org)
    session = new_id()
    await evidence.manager.write_policy(context(Role.OWNER, org), checkout_policy())
    evidence.work.deliver(org.id, session, delivered())
    with pytest.raises(ValidationFailed, match="do not hash"):
        await evidence.manager.validate(ctx, session, RunPurpose.VALIDATION)
    assert (await evidence.manager.get_runs(ctx, session, None, 10)).items == ()


class Elsewhere(ScriptedExecutor):
    """Writes its results at a version it was not asked for."""

    async def run(self, ctx: TenantContext, request: ExecutionRequest) -> ExecutorReport:
        return await super().run(ctx, request.model_copy(update={"version": "beef"}))


class Unasked(ScriptedExecutor):
    """Writes results of a check it was not asked for."""

    async def run(self, ctx: TenantContext, request: ExecutionRequest) -> ExecutorReport:
        checks = tuple(check.model_copy(update={"name": "lint"}) for check in request.checks)
        return await super().run(ctx, request.model_copy(update={"checks": checks}))


@pytest.mark.parametrize(
    ("executor", "why"),
    [(Elsewhere(), "not the c0ffee asked for"), (Unasked(), "lint 1, which was not asked for")],
)
async def test_results_of_a_check_or_a_version_not_asked_for_keep_nothing(
    executor: ScriptedExecutor, why: str
) -> None:
    org = make_org()
    ctx = context(Role.MEMBER, org)
    session = new_id()
    evidence = evidence_over(executor)
    await evidence.manager.write_policy(context(Role.OWNER, org), checkout_policy())
    evidence.work.deliver(org.id, session, delivered())
    with pytest.raises(ValidationFailed, match=why):
        await evidence.manager.validate(ctx, session, RunPurpose.VALIDATION)
    assert (await evidence.manager.get_runs(ctx, session, None, 10)).items == ()


class Overrun(ScriptedExecutor):
    """Runs each check one trial past the count it was asked for."""

    async def run(self, ctx: TenantContext, request: ExecutionRequest) -> ExecutorReport:
        trials = tuple(count + 1 for count in request.trials)
        return await super().run(ctx, request.model_copy(update={"trials": trials}))


@pytest.mark.parametrize(
    ("executor", "options", "why"),
    [
        (ScriptedExecutor(), EvidenceOptions(max_results_bytes=200), "past the 200 one"),
        (Overrun(), EvidenceOptions(), "2 runs of unit, past the 1 asked for"),
    ],
)
async def test_results_past_their_bytes_or_the_trials_asked_keep_nothing(
    executor: ScriptedExecutor, options: EvidenceOptions, why: str
) -> None:
    org = make_org()
    ctx = context(Role.MEMBER, org)
    session = new_id()
    evidence = evidence_over(executor, options)
    await evidence.manager.write_policy(context(Role.OWNER, org), checkout_policy())
    evidence.work.deliver(org.id, session, delivered())
    with pytest.raises(ValidationFailed, match=why):
        await evidence.manager.validate(ctx, session, RunPurpose.VALIDATION)
    assert (await evidence.manager.get_runs(ctx, session, None, 10)).items == ()
    assert await evidence.manager.get_validations(ctx, session, 10) == ()


async def test_validation_is_refused_before_anything_runs() -> None:
    org = make_org()
    evidence = evidence_over()
    ctx = context(Role.MEMBER, org)
    session = new_id()
    with pytest.raises(PreconditionFailed, match="no work product"):
        await evidence.manager.validate(ctx, session, RunPurpose.VALIDATION)
    evidence.work.deliver(org.id, session, delivered())
    with pytest.raises(PreconditionFailed, match="declares no validation policy"):
        await evidence.manager.validate(ctx, session, RunPurpose.VALIDATION)
    needs_browser = checkout_policy(Requirement(check="trials", paths=("src/**",)))
    await evidence.manager.write_policy(context(Role.OWNER, org), needs_browser)
    evidence.executor.capabilities = frozenset()
    with pytest.raises(PreconditionFailed, match="needs browser"):
        await evidence.manager.validate(ctx, session, RunPurpose.VALIDATION)
    assert evidence.executor.requests == [], "nothing was asked of the executor"


async def test_the_absent_ports_refuse_loudly() -> None:
    org = make_org()
    evidence = evidence_over()
    manager = EvidenceManagerImpl(
        evidence.storage,
        evidence.members,
        evidence.manager._relay,  # pyright: ignore[reportPrivateUsage]
        ExecutorAbsentImpl(),
        WorkProductAbsentImpl(),
        evidence.projects,
        EvidenceOptions(),
    )
    ctx = context(Role.MEMBER, org)
    with pytest.raises(Unavailable, match="reads no work product"):
        await manager.validate(ctx, new_id(), RunPurpose.VALIDATION)
    await manager.write_policy(context(Role.OWNER, org), checkout_policy())
    with pytest.raises(Unavailable, match="no executor"):
        await ExecutorAbsentImpl().offer(ctx)


async def test_the_purges_take_a_sessions_runs_and_an_expired_tenants_rows() -> None:
    org = make_org()
    evidence = evidence_over()
    ctx = context(Role.MEMBER, org)
    gone, kept = new_id(), new_id()
    await evidence.manager.write_policy(context(Role.OWNER, org), checkout_policy())
    for session in (gone, kept):
        await evidence.manager.record_run(ctx, make_record(session))
    assert await evidence.manager.purge_session(org.id, gone) == 1
    assert (await evidence.manager.get_runs(ctx, gone, None, 10)).items == ()
    assert len((await evidence.manager.get_runs(ctx, kept, None, 10)).items) == 1
    service = context(Role.SERVICE, org)
    assert await evidence.manager.purge_tenant(service) == 0, "a live tenant keeps its rows"
    evidence.members.expired = True
    assert await evidence.manager.purge_tenant(service) == 2
    assert await evidence.manager.purge_tenant(service) == 0
