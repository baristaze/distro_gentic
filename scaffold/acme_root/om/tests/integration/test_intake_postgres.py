"""Intake and automations over Postgres: a failing check on a session's
pull request wakes it as data, and fires an automation whose run starts a
session held to its share of the cost cap, recorded once. A schedule
fires once a slot however many workers tick it at once, and an
automation run as the tenant's automation principal acts on that
principal's role alone. A scheduled station job runs under the lease its
grant gives, one fencing token after another."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from contracts.intake import wired
from contracts.loops import reply, said, use

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.agents.types.run import RunEnd
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.automations.root import build_automations
from acme.om.automations.types.automation import (
    Action,
    ActionKind,
    Automation,
    Firing,
    Limits,
    Refusal,
    RunsAs,
    RunStatus,
    StationWork,
    Trigger,
    TriggerKind,
)
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, RequestContext, Role, TenantContext
from acme.om.evidence.types.provenance import Provenance
from acme.om.evidence.types.record import RunOutcome
from acme.om.intake.rules import described
from acme.om.intake.types.event import (
    Arrival,
    Author,
    AuthorKind,
    CheckState,
    FeedbackEvent,
    WorkNames,
)
from acme.om.intake.types.link import HandleKind
from acme.om.intake.types.route import Effect
from acme.om.root import build_managers
from acme.om.stations.types.job import JobReport, StationCommand
from acme.om.stations.types.station import Lab, Station, StationPool
from acme.om.steps.rules import message_step
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings
from acme.om.tenancy.rules import permissions_of

pytestmark = pytest.mark.integration

APP = AppContext(type=AppType.PORTAL, version="portal@test")


@pytest.fixture
async def storage(
    migration_settings: MigrationSettings, migrated: object
) -> AsyncIterator[StoragePostgresImpl]:
    root = StoragePostgresImpl(
        migration_settings.role_urls(),
        migration_settings.role_pools(),
        system_urls=migration_settings.system_role_urls(),
    )
    yield root
    await root.close()


async def an_owner(storage: StoragePostgresImpl, tmp_path: Path) -> TenantContext:
    settings = InfraSettings.model_validate(
        {"environment": "local", "buckets_root": tmp_path / "buckets"}
    )
    managers = build_managers(storage, InfraConfiguredImpl(settings))
    slug = f"ajax-{new_id().hex[-8:]}"
    owner, _ = await managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP),
        "Ajax",
        slug,
        f"ann-{slug}@example.test",
        "Ann",
    )
    return owner


async def test_a_failing_check_wakes_its_session_and_fires_a_bounded_run_over_postgres(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    owner = await an_owner(storage, tmp_path)
    platform = wired(tmp_path, storage=storage, owner=owner)
    session_id = await platform.start()
    await platform.intake.bind_work(owner, session_id, HandleKind.BRANCH, "agent/fix")
    said_first = message_step(new_id(), utcnow(), session_id, owner, "Fix the import.")
    await platform.managers.agent_sessions.receive(owner, session_id, [said_first])
    platform.anthropic.add(reply(said("Pushed the fix.")))
    assert (await platform.loops.run(owner, session_id)).end is RunEnd.ENDED
    # A person at the portal makes the automation, and it runs as them.
    creator = platform.person(Role.ADMIN)
    now = utcnow()
    automation = Automation(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=creator.user_id,
        updated_by=creator.user_id,
        name="triage failing checks",
        trigger=Trigger(kind=TriggerKind.EVENT, arrivals=("check",), effects=("wake_as_data",)),
        action=Action(
            kind=ActionKind.START_SESSION, brief="Find why.", agent_kind="steady", title="CI"
        ),
        limits=Limits(
            cost_cap_micros=100_000_000, run_cap_micros=50_000_000, rate=1, concurrency=1
        ),
    )
    await platform.automations.create_automation(creator, automation)
    check = FeedbackEvent(
        id=new_id(),
        integration="forge",
        provenance=Provenance.TWIN,
        arrival=Arrival.CHECK,
        author=Author(kind=AuthorKind.BOT, external_id="ci", name="ci"),
        names=WorkNames(branch="agent/fix"),
        check=CheckState.FAILED,
        text="tests/test_gripper.py::test_grip FAILED",
        occurred_at=now,
    )
    routed = await platform.intake.route(platform.service, check)
    assert (routed.effect, routed.session_id) == (Effect.WAKE_AS_DATA, session_id)
    woken = await platform.managers.agent_sessions.get_session(owner, session_id)
    assert woken.status is SessionStatus.PENDING
    firing = Firing(
        event_id=check.id,
        occurred_at=check.occurred_at,
        integration=check.integration,
        arrival=check.arrival.value,
        effect=routed.effect.value,
        text=described(check),
    )
    (run,) = await platform.automations.fire(platform.service, firing)
    assert run.status is RunStatus.STARTED and run.budget_id is not None
    assert await platform.automations.fire(platform.service, firing) == (run,)
    (limited,) = await platform.automations.fire(
        platform.service, firing.model_copy(update={"event_id": new_id()})
    )
    assert limited.status is RunStatus.REFUSED
    budget = await platform.managers.budgets.get_budget(owner, run.budget_id)
    assert budget.cost_micros == automation.limits.run_cap_micros


def every_hour(creator: TenantContext, runs_as: RunsAs = RunsAs.CREATOR) -> Automation:
    now = utcnow()
    return Automation(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=creator.user_id,
        updated_by=creator.user_id,
        name="the nightly check",
        trigger=Trigger(kind=TriggerKind.SCHEDULE, every=timedelta(hours=1)),
        action=Action(
            kind=ActionKind.START_SESSION,
            brief="Check the records.",
            agent_kind="steady",
            title="the nightly records",
        ),
        limits=Limits(
            cost_cap_micros=1_000_000_000, run_cap_micros=50_000_000, rate=10, concurrency=10
        ),
        runs_as=runs_as,
    )


async def test_a_schedule_fires_once_a_slot_across_several_workers_over_postgres(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    owner = await an_owner(storage, tmp_path)
    platform = wired(tmp_path, storage=storage, owner=owner)
    creator = platform.person(Role.ADMIN)
    mine = await platform.automations.create_automation(creator, every_hour(creator))
    # Four workers' sweeps, each its own automations manager over the one
    # database, tick the tenant at once, in each of two slots.
    workers = [
        build_automations(
            storage,
            platform.managers,
            project_required=False,
            principal_context=platform.members,
            clock=platform.clock,
        )
        for _ in range(4)
    ]
    for slot in (1, 2):
        await asyncio.gather(*(worker.tick(platform.service) for worker in workers))
        await asyncio.gather(*(worker.tick(platform.service) for worker in workers))
        runs = await platform.automations.get_runs(owner, mine.id, 10)
        assert len(runs) == slot and {r.status for r in runs} == {RunStatus.STARTED}
        page = await platform.managers.agent_sessions.get_sessions(owner, None, None, 100)
        started = [s for s in page.items if s.title == "the nightly records"]
        assert len(started) == slot
        assert {s.id for s in started} == {r.session_id for r in runs}
        platform.clock.now += timedelta(hours=1)


async def test_an_automation_run_as_the_automation_principal_holds_its_role_alone_over_postgres(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    owner = await an_owner(storage, tmp_path)
    platform = wired(tmp_path, storage=storage, owner=owner)
    creator = platform.person(Role.ADMIN)
    granted = await platform.automations.grant_principal(creator, Role.MEMBER)
    await platform.automations.create_automation(
        creator, every_hour(creator, RunsAs.AUTOMATION_PRINCIPAL)
    )
    (run,) = await platform.automations.tick(platform.service)
    assert run.status is RunStatus.STARTED and run.session_id is not None
    session = await platform.managers.agent_sessions.get_session(owner, run.session_id)
    assert session.created_by == granted.id != creator.user_id
    platform.anthropic.add(reply(use("lookup")), reply(said("Checked.")))
    assert (await platform.loops.run(platform.service, run.session_id)).end is RunEnd.ENDED
    assert platform.lookup.ran_as == [granted.id]
    live = await platform.principals(
        RequestContext(request_id=new_id(), app=APP),
        owner.org_id,
        Principal(kind=PrincipalKind.PERSON, id=granted.id),
    )
    assert (live.role, live.security.permissions) == (Role.MEMBER, permissions_of(Role.MEMBER))
    # A role that cannot start the work starts none, though its creator could.
    await platform.automations.grant_principal(creator, Role.VIEWER)
    platform.clock.now += timedelta(hours=1)
    (refused,) = await platform.automations.tick(platform.service)
    assert (refused.status, refused.refusal, refused.session_id) == (
        RunStatus.REFUSED,
        Refusal.ACTION,
        None,
    )


DAEMON = AppContext(type=AppType.API, version="station-daemon@test")


async def test_a_scheduled_station_job_runs_under_its_lease_one_token_after_another_over_postgres(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    owner = await an_owner(storage, tmp_path)
    platform = wired(tmp_path, storage=storage, owner=owner)
    stations, now = platform.managers.stations, utcnow()
    by = {"created_at": now, "updated_at": now, "created_by": owner.user_id}
    by["updated_by"] = owner.user_id
    lab = await stations.create_lab(owner, Lab(id=new_id(), **by, name="lab-1"))
    pool = await stations.create_pool(owner, StationPool(id=new_id(), **by, name="arms"))
    await stations.add_station(
        owner, Station(id=new_id(), **by, lab_id=lab.id, pool_id=pool.id, name="arm-1")
    )
    issued = await stations.issue_daemon_credential(owner, lab.id)
    daemon = await stations.authenticate(
        RequestContext(request_id=new_id(), app=DAEMON), issued.credential
    )
    work = StationWork(
        pool_id=pool.id,
        project="acme/firmware",
        candidate="4f0405f",
        procedure="smoke",
        procedure_version="v1",
        commands=(StationCommand(operation="apply", parameters={"speed": 0.5}),),
    )
    creator = platform.person(Role.ADMIN)
    smoke = await platform.automations.create_automation(
        creator,
        every_hour(creator).model_copy(
            update={"action": Action(kind=ActionKind.RUN_STATION_JOB, station=work)}
        ),
    )
    for token in (1, 2):
        await platform.automations.tick(platform.service)
        (run, *_) = await platform.automations.get_runs(owner, smoke.id, 10)
        assert run.status is RunStatus.STARTED and run.job_id is not None
        claimed = await stations.claim(RequestContext(request_id=new_id(), app=DAEMON), daemon, 1)
        assert claimed is not None and claimed.job is not None
        assert (claimed.job.id, claimed.job.token, claimed.job.commands) == (
            run.job_id,
            token,
            work.commands,
        )
        at = utcnow()
        report = JobReport(
            run_id=new_id(),
            outcome=RunOutcome.PASSED,
            started_at=at,
            finished_at=at,
            commands_run=1,
            adapter="twin:arm-1",
            provenance=Provenance.TWIN,
            daemon_version="station-daemon@test",
        )
        await stations.report(
            RequestContext(request_id=new_id(), app=DAEMON), daemon, run.job_id, report
        )
        platform.clock.now += timedelta(hours=1)
    # The next tick closes the second run: its job ran.
    await platform.automations.tick(platform.service)
    runs = await platform.automations.get_runs(owner, smoke.id, 10)
    assert sum(1 for run in runs if run.closed_at is not None) == 2
