"""The result gate refuses a success that changed the work product unless
the validation policy passed at the committed head, on a clean tree, on
results its executor wrote; a run that validated nothing is inconclusive.
A double's run is never validation, and a twin's never stands for real.
A change that touches a protected path voids validation."""

from pathlib import Path
from uuid import UUID

import pytest
from contracts.doubles import context
from contracts.evidence import (
    CHECKOUT_KEY,
    Evidence,
    ScriptedExecutor,
    checkout_policy,
    delivered,
    evidence_over,
)
from contracts.evidence_storage import make_record, make_validation
from contracts.factories import make_org
from contracts.loops import DELIVERY

from acme.infra.impl.local import InfraLocalImpl
from acme.om.agents.impl.gate import ResultGateNullImpl
from acme.om.agents.impl.manager import AgentsManagerImpl
from acme.om.agents.types.request import Start
from acme.om.agents.types.result import Claim, Result, Verdict
from acme.om.base import new_id
from acme.om.context import Role, TenantContext
from acme.om.evidence.impl.gate import ResultGateEvidenceImpl
from acme.om.evidence.impl.ports import WorkProductAbsentImpl
from acme.om.evidence.types.policy import Grade, Requirement
from acme.om.evidence.types.provenance import Dependency, Provenance
from acme.om.evidence.types.rate import AbortRule, Bound, RateRule
from acme.om.evidence.types.record import RunPurpose
from acme.om.exceptions import PreconditionFailed, UnsafeConfiguration
from acme.om.root import build_managers
from acme.om.steps.types.header import LoopOutcome
from acme.om.storage.impl.memory import StorageMemoryImpl


class Case:
    """One session of the `checkout` project: its policy written, a work run of
    the agent's to cite, and its work product as the case delivers it."""

    def __init__(self, evidence: Evidence, ctx: TenantContext) -> None:
        self.evidence = evidence
        self.ctx = ctx
        self.session = new_id()
        self.run = make_record(self.session, step_id=new_id())

    @classmethod
    async def start(
        cls, executor: ScriptedExecutor | None = None, *requirements: Requirement
    ) -> Case:
        org = make_org()
        case = cls(evidence_over(executor), context(Role.MEMBER, org))
        owner = context(Role.OWNER, org)
        await case.evidence.manager.write_policy(owner, checkout_policy(*requirements))
        await case.evidence.manager.record_run(case.ctx, case.run)
        case.deliver()
        return case

    def deliver(self, **changes: object) -> None:
        self.evidence.work.deliver(self.ctx.org_id, self.session, delivered(**changes))  # type: ignore[arg-type]

    async def validate(self) -> None:
        await self.evidence.manager.validate(self.ctx, self.session, RunPurpose.VALIDATION)

    async def submit(self, claim: Claim = Claim.SUCCEEDED, *cited: UUID) -> Verdict:
        result = Result(claim=claim, evidence=cited or (self.run.id,))
        return await self.evidence.gate.check(self.ctx, self.session, result)


def succeeded(verdict: Verdict) -> bool:
    return verdict.accepted and verdict.verified and verdict.outcome is LoopOutcome.SUCCEEDED


def refused(verdict: Verdict, *words: str) -> bool:
    reason = verdict.reason or ""
    return not verdict.accepted and all(word in reason for word in words)


# Check 2: the gate.


async def test_a_delivery_is_judged_by_its_sessions_project_whatever_it_names() -> None:
    """The work product names a project; the gate and the validation read
    the session's own, from the projects, and judge by its policy: `checkout`'s
    asks for the unit check of a change under `src/`, the other's for none."""
    org = make_org()
    evidence = evidence_over()
    owner, ctx = context(Role.OWNER, org), context(Role.MEMBER, org)
    other = new_id()
    await evidence.manager.write_policy(owner, checkout_policy())
    await evidence.manager.write_policy(
        owner, checkout_policy(Requirement(check="unit", paths=("docs/**",)), project=other)
    )
    ours, theirs = new_id(), new_id()  # a session of `checkout`, and one of the other
    evidence.projects.sessions[theirs] = other
    for session_id, named in ((ours, str(other)), (theirs, CHECKOUT_KEY)):
        delivery = delivered().model_copy(update={"project": named})
        evidence.work.deliver(org.id, session_id, delivery)
    runs = {s: make_record(s, step_id=new_id()) for s in (ours, theirs)}
    for run in runs.values():
        await evidence.manager.record_run(ctx, run)

    async def submit(session_id: UUID) -> Verdict:
        result = Result(claim=Claim.SUCCEEDED, evidence=(runs[session_id].id,))
        return await evidence.gate.check(ctx, session_id, result)

    assert refused(await submit(ours), "no validation ran at the head c0ffee")
    validation = await evidence.manager.validate(ctx, ours, RunPurpose.VALIDATION)
    assert validation.project == CHECKOUT_KEY, "validated under the session's project"
    assert [check.name for check in evidence.executor.requests[0].checks] == ["unit"]
    assert succeeded(await submit(ours))

    verdict = await submit(theirs)
    assert verdict.accepted and verdict.outcome is LoopOutcome.INCONCLUSIVE, "nothing asked"


async def test_a_success_the_policy_passed_at_the_head_counts() -> None:
    case = await Case.start()
    await case.validate()
    assert succeeded(await case.submit())
    # A citation by the agent's step, or by the validation, finds its runs too.
    assert succeeded(await case.submit(Claim.SUCCEEDED, case.run.step_id or new_id()))


async def test_a_success_with_no_validation_at_its_head_is_refused() -> None:
    case = await Case.start()
    assert refused(await case.submit(), "no validation ran at the head c0ffee")
    await case.validate()
    # A commit after the validation is a head nobody validated.
    case.deliver(head="d00d")
    assert refused(await case.submit(), "no validation ran at the head d00d")


async def test_a_success_on_a_dirty_tree_is_refused_and_validation_too() -> None:
    case = await Case.start()
    await case.validate()
    case.deliver(dirty=True)
    assert refused(await case.submit(), "uncommitted changes")
    with pytest.raises(PreconditionFailed, match="uncommitted changes"):
        await case.validate()


async def test_a_success_on_runs_its_executor_did_not_write_is_refused() -> None:
    case = await Case.start()
    storage, org = case.evidence.storage, case.ctx.org_id
    # Runs another writer wrote, listed by a validation that names the
    # executor: their provenance does not name it.
    validation, runs = make_validation(case.session, 1, executor="executor-1", project=CHECKOUT_KEY)
    forged = tuple(run.model_copy(update={"executor": "agent-workspace"}) for run in runs)
    assert await storage.create_validation(org, validation, forged)
    assert refused(await case.submit(), "not a result its validation's executor wrote")


async def test_a_success_on_runs_the_validation_does_not_list_is_refused() -> None:
    case = await Case.start()
    await case.validate()
    storage, org = case.evidence.storage, case.ctx.org_id
    (validation,) = await storage.read_validations(org, case.session, None, 10)
    stray = make_record(
        case.session,
        purpose=RunPurpose.VALIDATION,
        validation_id=validation.id,
        executor="executor-1",
    )
    assert await storage.create_record(org, stray)
    assert refused(await case.submit(), "lists runs other than the ones stored with it")


async def test_a_validation_that_failed_is_refused_and_a_pass_after_it_still_counts_it() -> None:
    failing = ScriptedExecutor(outcome=lambda check, trial: "failed")
    case = await Case.start(failing)
    await case.validate()
    assert refused(await case.submit(), "did not pass", "unit did not pass in 1 of 1 runs")
    # Run again until it passes: every run at the head is still counted.
    failing.outcome = lambda check, trial: "passed"
    await case.validate()
    assert refused(await case.submit(), "unit did not pass in 1 of 2 runs")


async def test_a_run_that_validated_nothing_is_inconclusive() -> None:
    case = await Case.start()
    # Nothing changed: the head is the base.
    case.deliver(head="base0", changed=())
    verdict = await case.submit()
    assert verdict.accepted and verdict.outcome is LoopOutcome.INCONCLUSIVE
    # A change the policy asks no check of: nothing to validate either.
    case.deliver(changed=("docs/notes.md",))
    with pytest.raises(PreconditionFailed, match="nothing to validate"):
        await case.validate()
    verdict = await case.submit()
    assert verdict.accepted and verdict.outcome is LoopOutcome.INCONCLUSIVE
    assert verdict.verified, "the gate judged it: it is inconclusive, not unchecked"


async def test_a_session_with_no_work_product_validates_nothing() -> None:
    case = await Case.start()
    case.evidence.work = type(case.evidence.work)()
    gate = ResultGateEvidenceImpl(case.evidence.storage, case.evidence.work, case.evidence.projects)
    verdict = await gate.check(
        case.ctx, case.session, Result(claim=Claim.SUCCEEDED, evidence=(case.run.id,))
    )
    assert verdict.accepted and verdict.outcome is LoopOutcome.INCONCLUSIVE


async def test_a_failure_explained_by_runs_is_a_result() -> None:
    case = await Case.start()
    verdict = await case.submit(Claim.FAILED)
    assert verdict.accepted and verdict.outcome is LoopOutcome.FAILED


async def test_a_claim_that_cites_no_run_of_its_session_is_refused() -> None:
    case = await Case.start()
    other = make_record(new_id())
    assert await case.evidence.storage.create_record(case.ctx.org_id, other)
    for claim in Claim:
        assert refused(await case.submit(claim, new_id()), "names no run of this session")
        assert refused(await case.submit(claim, other.id), "names no run of this session")
        assert refused(await case.submit(claim, case.run.id, new_id()), "names no run")
    too_many = tuple(new_id() for _ in range(501))
    assert refused(await case.submit(Claim.SUCCEEDED, *too_many), "at most 500")


async def test_a_gate_that_cannot_read_the_work_product_counts_no_success() -> None:
    case = await Case.start()
    await case.validate()
    gate = ResultGateEvidenceImpl(
        case.evidence.storage, WorkProductAbsentImpl(), case.evidence.projects
    )
    result = Result(claim=Claim.SUCCEEDED, evidence=(case.run.id,))
    assert refused(await gate.check(case.ctx, case.session, result), "reads no work product")
    failed = Result(claim=Claim.FAILED, evidence=(case.run.id,))
    assert (await gate.check(case.ctx, case.session, failed)).outcome is LoopOutcome.FAILED


async def test_a_project_with_no_policy_counts_no_success() -> None:
    case = await Case.start()
    # A project that declares no policy, then no project at all.
    for project in (new_id(), None):
        case.evidence.projects.sessions[case.session] = project
        assert refused(await case.submit(), "declares no validation policy")


# Check 1: a double is never validation, and a twin never real.


async def test_a_doubles_passing_run_is_never_validation() -> None:
    case = await Case.start(ScriptedExecutor(provenance=Provenance.DOUBLE))
    await case.validate()
    assert refused(await case.submit(), "no passing run at the twin grade")


async def test_a_twins_passing_run_never_stands_for_a_real_one() -> None:
    real = Requirement(check="unit", grade=Grade.REAL, paths=("src/**",))
    case = await Case.start(ScriptedExecutor(provenance=Provenance.TWIN), real)
    await case.validate()
    assert refused(await case.submit(), "no passing run at the real grade")
    runs = (await case.evidence.manager.get_runs(case.ctx, case.session, None, 10)).items
    assert {run.provenance for run in runs if run.purpose is RunPurpose.VALIDATION} == {
        Provenance.TWIN
    }


async def test_a_twin_passes_where_the_policy_accepts_a_twin() -> None:
    case = await Case.start(ScriptedExecutor(provenance=Provenance.TWIN))
    await case.validate()
    assert succeeded(await case.submit())


def test_a_run_reports_its_weakest_dependency_and_never_claims_real() -> None:
    run = make_record(new_id())
    served = run.model_copy(
        update={
            "dependencies": (
                Dependency(name="browser", provenance=Provenance.REAL),
                Dependency(name="payments-api", provenance=Provenance.TWIN),
            )
        }
    )
    assert served.provenance is Provenance.TWIN
    doubled = served.model_copy(
        update={
            "dependencies": (
                *served.dependencies,
                Dependency(name="db", provenance=Provenance.DOUBLE),
            )
        }
    )
    assert doubled.provenance is Provenance.DOUBLE
    with pytest.raises(ValueError, match="Extra inputs"):
        type(run).model_validate({**served.model_dump(), "provenance": "real"})


# Check 3: a change that touches a protected path voids validation.


async def test_a_change_touching_a_protected_path_voids_validation() -> None:
    case = await Case.start()
    await case.validate()
    assert succeeded(await case.submit())
    # The same head, read again with the test the agent changed beside it.
    case.deliver(changed=("src/cart.py", "tests/test_cart.py"))
    assert refused(await case.submit(), "touches protected paths", "voids validation")
    with pytest.raises(PreconditionFailed, match="voids validation"):
        await case.validate()
    # Spelled another way, it is the same path.
    case.deliver(changed=("src/cart.py", "./Tests//test_cart.py"))
    assert refused(await case.submit(), "touches protected paths")
    case.deliver(changed=("src/cart.py", "src/../tests/test_cart.py"))
    assert refused(await case.submit(), "touches protected paths")


# Statistical evidence at the gate.


def trials(
    count: int, max_rate: float = 0.02, aborted: AbortRule = AbortRule.FAILURE
) -> Requirement:
    rule = RateRule(max_rate=max_rate, confidence=0.95, trials=count, aborted=aborted)
    return Requirement(check="trials", paths=("src/**",), rate=rule)


async def test_a_rate_requirement_counts_every_trial_and_bounds_the_rate() -> None:
    case = await Case.start(ScriptedExecutor(), trials(300))
    await case.validate()
    assert succeeded(await case.submit())
    (request,) = case.evidence.executor.requests
    assert request.trials == (300,) and [check.name for check in request.checks] == ["trials"]


async def test_a_rate_above_its_bound_is_refused() -> None:
    flaky = ScriptedExecutor(outcome=lambda check, trial: "failed" if trial < 5 else "passed")
    case = await Case.start(flaky, trials(300))
    await case.validate()
    assert refused(await case.submit(), "the failure rate is at most", "above the 2.00% declared")


async def test_an_aborted_trial_is_classified_by_the_declared_rule() -> None:
    stops = ScriptedExecutor(outcome=lambda check, trial: "aborted" if trial == 0 else "passed")
    case = await Case.start(stops, trials(300, aborted=AbortRule.INCONCLUSIVE))
    await case.validate()
    assert refused(await case.submit(), "1 trials an abort ended")
    counted = await Case.start(
        ScriptedExecutor(outcome=lambda check, trial: "aborted" if trial == 0 else "passed"),
        trials(300, max_rate=0.01),
    )
    await counted.validate()
    # Counted as a failure, the one abort lifts the bound past 1%.
    assert refused(await counted.submit(), "1 failures in 300 trials")


async def test_two_rates_judged_together_take_a_corrected_confidence() -> None:
    rule = RateRule(max_rate=0.2, confidence=0.95, trials=10)
    both = (trials(10, max_rate=0.2), Requirement(check="unit", paths=("src/**",), rate=rule))
    flaky = ScriptedExecutor(outcome=lambda check, trial: "failed" if trial < 1 else "passed")
    case = await Case.start(flaky, *both)
    await case.validate()
    assert refused(await case.submit(), "one-sided 97.5%")


async def test_fewer_trials_than_declared_are_refused() -> None:
    case = await Case.start(ScriptedExecutor(), trials(300))
    storage, org = case.evidence.storage, case.ctx.org_id
    validation, runs = make_validation(case.session, 3, project=CHECKOUT_KEY)
    moved = tuple(run.model_copy(update={"check": "trials"}) for run in runs)
    assert await storage.create_validation(org, validation, moved)
    assert refused(await case.submit(), "trials ran 3 of the 300 trials declared")


# The sequential test stops where its rule says; a fixed count never early.


def sequential(most: int = 200) -> Requirement:
    rule = RateRule(
        max_rate=0.1, confidence=0.95, bound=Bound.SEQUENTIAL, trials=most, alternative=0.02
    )
    return Requirement(check="trials", paths=("src/**",), rate=rule)


async def test_a_sequential_test_stops_at_its_boundary_and_its_claim_counts() -> None:
    case = await Case.start(ScriptedExecutor(), sequential())
    await case.validate()
    (request,) = case.evidence.executor.requests
    assert request.trials == (200,) and request.rates == (sequential().rate,)
    runs = (await case.evidence.manager.get_runs(case.ctx, case.session, None, 200)).items
    # Clean trials bound the rate under 10% at the 36th, and the executor
    # stopped there.
    assert len([run for run in runs if run.check == "trials"]) == 36
    assert succeeded(await case.submit())


async def test_a_sequential_test_stopped_anywhere_else_is_refused() -> None:
    for count, words in (
        (20, ("ran 20 trials", "had not stopped")),
        (50, ("ran 50 trials, on past trial 36", "where its sequential test stopped")),
    ):
        case = await Case.start(ScriptedExecutor(), sequential())
        validation, runs = make_validation(case.session, count, project=CHECKOUT_KEY)
        moved = tuple(run.model_copy(update={"check": "trials"}) for run in runs)
        assert await case.evidence.storage.create_validation(case.ctx.org_id, validation, moved)
        assert refused(await case.submit(), *words)


async def test_a_sequential_test_that_cannot_bound_the_rate_stops_and_is_refused() -> None:
    flaky = ScriptedExecutor(outcome=lambda check, trial: "failed" if trial == 0 else "passed")
    case = await Case.start(flaky, sequential(most=40))
    await case.validate()
    runs = (await case.evidence.manager.get_runs(case.ctx, case.session, None, 200)).items
    # One failure first: no 39 clean trials could bound it, so it stops.
    assert len([run for run in runs if run.check == "trials"]) == 1
    assert refused(await case.submit(), "1 failures in 1 trials", "sequential bound")


async def test_a_fixed_count_claim_runs_every_trial_and_refuses_to_stop_early() -> None:
    case = await Case.start(ScriptedExecutor(), trials(50, max_rate=0.1))
    await case.validate()
    runs = (await case.evidence.manager.get_runs(case.ctx, case.session, None, 200)).items
    # Where a sequential test would have stopped at 36, the count runs on.
    assert len([run for run in runs if run.check == "trials"]) == 50
    assert succeeded(await case.submit())
    stopped = await Case.start(ScriptedExecutor(), trials(50, max_rate=0.1))
    validation, early = make_validation(stopped.session, 36, project=CHECKOUT_KEY)
    moved = tuple(run.model_copy(update={"check": "trials"}) for run in early)
    assert await stopped.evidence.storage.create_validation(stopped.ctx.org_id, validation, moved)
    assert refused(await stopped.submit(), "trials ran 36 of the 50 trials declared")


def test_a_sequential_test_is_its_checks_one_rate() -> None:
    fixed = trials(300)
    with pytest.raises(ValueError, match="sequential test declares no other rate"):
        checkout_policy(sequential(), fixed)


# A run that passed no case is no passing run.


@pytest.mark.parametrize("cases", [("skipped", "skipped"), ()])
async def test_a_run_that_passed_no_case_is_no_passing_run(cases: tuple[str, ...]) -> None:
    case = await Case.start(ScriptedExecutor(cases=cases))
    await case.validate()
    runs = (await case.evidence.manager.get_runs(case.ctx, case.session, None, 10)).items
    validated = [run for run in runs if run.purpose is RunPurpose.VALIDATION]
    assert [run.cases.passed for run in validated] == [0] and not validated[0].passing
    assert refused(await case.submit(), "unit did not pass in 1 of 1 runs")


# A rate is judged a batch at a time: validating again until it holds never passes.


async def test_a_failed_batch_stays_counted_after_a_clean_one() -> None:
    flaky = ScriptedExecutor(outcome=lambda check, trial: "failed" if trial == 0 else "passed")
    case = await Case.start(flaky, trials(300, max_rate=0.01))
    await case.validate()
    assert refused(await case.submit(), "1 failures in 300 trials")
    # A clean batch alone would hold, and the two pooled (1 in 600) would too.
    flaky.outcome = lambda check, trial: "passed"
    await case.validate()
    assert refused(await case.submit(), "1 failures in 300 trials", "above the 1.00% declared")
    clean = await Case.start(ScriptedExecutor(), trials(300, max_rate=0.01))
    await clean.validate()
    assert succeeded(await clean.submit())


# The root wires this gate, and a deployed root refuses the null one.


@pytest.mark.parametrize("environment", ["staging", "production", "test"])
def test_a_deployed_root_refuses_a_quiet_null_result_gate(environment: str, tmp_path: Path) -> None:
    with pytest.raises(UnsafeConfiguration, match="ResultGateNullImpl"):
        build_managers(
            StorageMemoryImpl(),
            InfraLocalImpl(tmp_path),
            result_gate=ResultGateNullImpl(),
            environment=environment,
        )
    local = build_managers(
        StorageMemoryImpl(), InfraLocalImpl(tmp_path), result_gate=ResultGateNullImpl()
    )
    assert isinstance(local.agents, AgentsManagerImpl)


async def test_a_root_given_no_gate_ends_every_success_through_the_evidence_gate(
    tmp_path: Path,
) -> None:
    managers = build_managers(
        StorageMemoryImpl(),
        InfraLocalImpl(tmp_path),
        agent_kinds=(DELIVERY,),
        environment="staging",
    )
    ctx = context(Role.MEMBER)
    session = await managers.agents.start_session(
        ctx, Start(id=new_id(), kind="delivery", title="fix the cart")
    )
    run = make_record(session.id)
    await managers.evidence.record_run(ctx, run)
    verdict = await managers.agents.judge_result(
        ctx, session.id, Result(claim=Claim.SUCCEEDED, evidence=(run.id,))
    )
    # Nothing says what the session delivered, so no success counts.
    assert refused(verdict, "cannot read what it judges")
    bare = Result(claim=Claim.SUCCEEDED, evidence=(new_id(),))
    assert refused(await managers.agents.judge_result(ctx, session.id, bare), "names no run")
