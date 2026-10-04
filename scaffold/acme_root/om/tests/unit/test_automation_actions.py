"""A product's own kind of automation action: its kind acts in the firing,
as the automation runs, and the run it started stays at work until the
kind's check says that work ended, whatever time passes, then closes as
the check says. An action that names a kind no product declares is refused
when it is written, and a product's kind named as one of the platform's
actions is refused at boot."""

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest
from contracts.intake import Wired, wired
from pydantic import Field, ValidationError

from acme.om.automations.actions import AutomationActionInterface
from acme.om.automations.impl.manager import AutomationsOptions
from acme.om.automations.types.automation import (
    Action,
    ActionKind,
    Automation,
    AutomationRun,
    Firing,
    Limits,
    Refusal,
    RunOutcome,
    RunStatus,
    Trigger,
    TriggerKind,
)
from acme.om.base import Platform, derived_id, new_id, utcnow
from acme.om.context import Role, TenantContext
from acme.om.exceptions import ValidationFailed
from acme.om.root import Managers

JOB = "run_job"


class Job(Platform):
    steps: int = Field(ge=1, le=10)


class JobAction(AutomationActionInterface):
    """A product's kind that writes a job of its own and reads how it went:
    a ledger stands in for the product's own store."""

    params = Job

    def __init__(self, name: str = JOB) -> None:
        self.name = name
        self.jobs: dict[UUID, RunOutcome | None] = {}
        self.acted_as: list[UUID] = []
        self.texts: list[str] = []
        self.broken = False

    async def act(self, ctx: TenantContext, run: AutomationRun, params: Platform) -> UUID:
        assert isinstance(params, Job)
        job_id = derived_id(run.id, run.created_at, "job")
        self.jobs.setdefault(job_id, None)
        self.acted_as.append(ctx.user_id)
        self.texts.append(run.event_text)
        return job_id

    async def ended(self, ctx: TenantContext, run: AutomationRun) -> RunOutcome | None:
        if self.broken:
            raise RuntimeError("the product's store is down")
        assert run.work_id is not None
        return self.jobs[run.work_id]


def declaring(
    *kinds: AutomationActionInterface,
) -> Callable[..., tuple[AutomationActionInterface, ...]]:
    def actions(managers: Callable[[], Managers]) -> tuple[AutomationActionInterface, ...]:
        return kinds

    return actions


def job_automation(**changes: object) -> Automation:
    now = utcnow()
    return Automation(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=new_id(),
        updated_by=new_id(),
        name="run the job on each comment",
        trigger=Trigger(kind=TriggerKind.EVENT, arrivals=("comment",)),
        action=Action(kind=JOB, params={"steps": 2}),
        limits=Limits(cost_cap_micros=1000, run_cap_micros=10, rate=100, concurrency=1),
    ).model_copy(update=changes)


def comment() -> Firing:
    return Firing(
        event_id=new_id(),
        occurred_at=utcnow(),
        integration="forge",
        arrival="comment",
        text="Run it again.",
    )


async def fired(platform: Wired) -> AutomationRun:
    (run,) = await platform.automations.fire(platform.service, comment())
    return run


async def runs_of(platform: Wired, automation: Automation) -> dict[UUID, AutomationRun]:
    found = await platform.automations.get_runs(platform.owner, automation.id, 50)
    return {run.id: run for run in found}


@pytest.fixture
def job() -> JobAction:
    return JobAction()


@pytest.fixture
def platform(tmp_path: Path, job: JobAction) -> Wired:
    return wired(tmp_path, actions=declaring(job))


async def test_a_products_action_acts_in_the_firing_and_its_run_closes_as_its_check_says(
    platform: Wired, job: JobAction
) -> None:
    creator = platform.person(Role.ADMIN)
    made = await platform.automations.create_automation(creator, job_automation())
    first = await fired(platform)
    # Acted before the firing answered, as its creator, with the event as data.
    assert first.status is RunStatus.STARTED and first.session_id is None
    assert first.work_id is not None and first.work_id in job.jobs
    assert (job.acted_as, job.texts) == ([creator.user_id], ["Run it again."])
    # Long past the time a session-less run counts as lost, its job still
    # runs: the run stays at work and holds the concurrency of one.
    platform.clock.now += AutomationsOptions().lost_after * 3
    held = await fired(platform)
    assert (held.status, held.refusal) == (RunStatus.REFUSED, Refusal.CONCURRENCY)
    assert (await runs_of(platform, made))[first.id].closed_at is None
    # A check that fails says nothing of the job, so the run stays open.
    job.broken = True
    assert (await fired(platform)).refusal is Refusal.CONCURRENCY
    job.broken = False
    # The check says it succeeded: the run closes so, and the next one starts.
    job.jobs[first.work_id] = RunOutcome.SUCCEEDED
    second = await fired(platform)
    assert second.status is RunStatus.STARTED and second.work_id is not None
    closed = (await runs_of(platform, made))[first.id]
    assert closed.closed_at is not None and closed.outcome is RunOutcome.SUCCEEDED
    job.jobs[second.work_id] = RunOutcome.FAILED
    assert (await fired(platform)).status is RunStatus.STARTED
    assert (await runs_of(platform, made))[second.id].outcome is RunOutcome.FAILED


async def test_an_action_of_a_kind_no_product_declares_is_refused_when_written(
    platform: Wired,
) -> None:
    creator = platform.person(Role.ADMIN)
    with pytest.raises(ValidationFailed, match="no product declares"):
        await platform.automations.create_automation(
            creator, job_automation(action=Action(kind="run_test", params={"steps": 2}))
        )
    with pytest.raises(ValidationFailed, match="malformed"):
        await platform.automations.create_automation(
            creator, job_automation(action=Action(kind=JOB, params={"steps": 0}))
        )
    made = await platform.automations.create_automation(creator, job_automation())
    with pytest.raises(ValidationFailed, match="no product declares"):
        await platform.automations.update_automation(
            creator, made.id, job_automation(action=Action(kind="run_test"))
        )
    assert await platform.automations.list_automations(creator, None, 10) == (made,)
    # A product's action carries no session's fields, and a session's no params.
    with pytest.raises(ValidationError):
        Action(kind=JOB, brief="Run it.")
    with pytest.raises(ValidationError):
        Action(kind=ActionKind.MESSAGE_SESSION, brief="Look.", session_id=new_id(), params={"a": 1})
    with pytest.raises(ValidationError):
        Action(kind=JOB, params={"blob": "x" * 20_001})


async def test_an_automation_whose_kind_left_the_product_is_refused_at_each_firing(
    tmp_path: Path,
) -> None:
    platform = wired(tmp_path)
    stored = job_automation(created_by=platform.owner.user_id)
    await platform.storage.get_automation_storage().create_automation(
        platform.owner.org_id, stored, ()
    )
    run = await fired(platform)
    assert (run.status, run.refusal, run.work_id) == (RunStatus.REFUSED, Refusal.ACTION, None)


@pytest.mark.parametrize("kind", [ActionKind.START_SESSION, ActionKind.MESSAGE_SESSION])
def test_a_products_kind_named_as_the_platforms_action_is_refused_at_boot(
    tmp_path: Path, kind: ActionKind
) -> None:
    with pytest.raises(ValueError, match="the platform's action"):
        wired(tmp_path, actions=declaring(JobAction(kind.value)))


def test_a_products_kind_registered_twice_is_refused_at_boot(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="registered twice"):
        wired(tmp_path, actions=declaring(JobAction(), JobAction()))
    with pytest.raises(ValueError, match="lower case"):
        wired(tmp_path, actions=declaring(JobAction("Run Job")))
