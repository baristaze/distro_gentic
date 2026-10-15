"""Intake and agent automations over Postgres: a failing check on a session's
pull request wakes it as data, and fires an agent automation whose run starts a
session held to its share of the cost cap, recorded once. A schedule
fires once a slot however many workers tick it at once, and an
agent automation run as the tenant's agent automation principal acts on that
principal's role alone."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.om.agent_automations.root import build_agent_automations
from acme.om.agent_automations.types.agent_automation import (
    Action,
    ActionKind,
    AgentAutomation,
    Firing,
    Limits,
    Refusal,
    RunsAs,
    RunStatus,
    Trigger,
    TriggerKind,
)
from acme.om.agent_sessions.types.agent_session import AgentSessionStatus
from acme.om.agent_steps.rules import message_step
from acme.om.agents.types.run import RunEnd
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, RequestContext, Role, TenantContext
from acme.om.evidence.types.provenance import Provenance
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
from acme.om.platform_root import build_platform_managers
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings
from acme.om.tenancy.rules import permissions_of

from contracts.intake import wired
from contracts.loops import reply, said, use

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
    managers = build_platform_managers(storage, InfraConfiguredImpl(settings))
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
    agent_session_id = await platform.start()
    await platform.intake.bind_work(owner, agent_session_id, HandleKind.BRANCH, "agent/fix")
    said_first = message_step(new_id(), utcnow(), agent_session_id, owner, "Fix the import.")
    await platform.managers.agent_sessions.receive(owner, agent_session_id, [said_first])
    platform.anthropic.add(reply(said("Pushed the fix.")))
    assert (await platform.loops.run(owner, agent_session_id)).end is RunEnd.ENDED
    # A person at the portal makes the agent automation, and it runs as them.
    creator = platform.person(Role.ADMIN)
    now = utcnow()
    agent_automation = AgentAutomation(
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
    await platform.agent_automations.create_agent_automation(creator, agent_automation)
    check = FeedbackEvent(
        id=new_id(),
        integration="forge",
        provenance=Provenance.TWIN,
        arrival=Arrival.CHECK,
        author=Author(kind=AuthorKind.BOT, external_id="ci", name="ci"),
        names=WorkNames(branch="agent/fix"),
        check=CheckState.FAILED,
        text="tests/test_payments.py::test_refund FAILED",
        occurred_at=now,
    )
    routed = await platform.intake.route(platform.service, check)
    assert (routed.effect, routed.agent_session_id) == (Effect.WAKE_AS_DATA, agent_session_id)
    woken = await platform.managers.agent_sessions.get_agent_session(owner, agent_session_id)
    assert woken.status is AgentSessionStatus.PENDING
    firing = Firing(
        event_id=check.id,
        occurred_at=check.occurred_at,
        integration=check.integration,
        arrival=check.arrival.value,
        effect=routed.effect.value,
        text=described(check),
    )
    (run,) = await platform.agent_automations.fire(platform.service, firing)
    assert run.status is RunStatus.STARTED and run.spend_budget_id is not None
    assert await platform.agent_automations.fire(platform.service, firing) == (run,)
    (limited,) = await platform.agent_automations.fire(
        platform.service, firing.model_copy(update={"event_id": new_id()})
    )
    assert limited.status is RunStatus.REFUSED
    budget = await platform.managers.spend_budgets.get_spend_budget(owner, run.spend_budget_id)
    assert budget.cost_micros == agent_automation.limits.run_cap_micros


def every_hour(creator: TenantContext, runs_as: RunsAs = RunsAs.CREATOR) -> AgentAutomation:
    now = utcnow()
    return AgentAutomation(
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
    mine = await platform.agent_automations.create_agent_automation(creator, every_hour(creator))
    # Four workers' sweeps, each its own agent automations manager over the one
    # database, tick the tenant at once, in each of two slots.
    workers = [
        build_agent_automations(
            storage,
            platform.managers,
            agent_project_required=False,
            principal_context=platform.members,
            clock=platform.clock,
        )
        for _ in range(4)
    ]
    for slot in (1, 2):
        await asyncio.gather(*(worker.tick(platform.service) for worker in workers))
        await asyncio.gather(*(worker.tick(platform.service) for worker in workers))
        runs = await platform.agent_automations.get_runs(owner, mine.id, 10)
        assert len(runs) == slot and {r.status for r in runs} == {RunStatus.STARTED}
        page = await platform.managers.agent_sessions.get_agent_sessions(owner, None, None, 100)
        started = [s for s in page.items if s.title == "the nightly records"]
        assert len(started) == slot
        assert {s.id for s in started} == {r.agent_session_id for r in runs}
        platform.clock.now += timedelta(hours=1)


async def test_an_agent_automation_run_as_the_agent_automation_principal_holds_its_role_alone_over_postgres(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    owner = await an_owner(storage, tmp_path)
    platform = wired(tmp_path, storage=storage, owner=owner)
    creator = platform.person(Role.ADMIN)
    granted = await platform.agent_automations.grant_principal(creator, Role.MEMBER)
    await platform.agent_automations.create_agent_automation(
        creator, every_hour(creator, RunsAs.AGENT_AUTOMATION_PRINCIPAL)
    )
    (run,) = await platform.agent_automations.tick(platform.service)
    assert run.status is RunStatus.STARTED and run.agent_session_id is not None
    session = await platform.managers.agent_sessions.get_agent_session(owner, run.agent_session_id)
    assert session.created_by == granted.id != creator.user_id
    platform.anthropic.add(reply(use("lookup")), reply(said("Checked.")))
    assert (await platform.loops.run(platform.service, run.agent_session_id)).end is RunEnd.ENDED
    assert platform.lookup.ran_as == [granted.id]
    live = await platform.principals(
        RequestContext(request_id=new_id(), app=APP),
        owner.org_id,
        Principal(kind=PrincipalKind.PERSON, id=granted.id),
    )
    assert (live.role, live.security.permissions) == (Role.MEMBER, permissions_of(Role.MEMBER))
    # A role that cannot start the work starts none, though its creator could.
    await platform.agent_automations.grant_principal(creator, Role.VIEWER)
    platform.clock.now += timedelta(hours=1)
    (refused,) = await platform.agent_automations.tick(platform.service)
    assert (refused.status, refused.refusal, refused.agent_session_id) == (
        RunStatus.REFUSED,
        Refusal.ACTION,
        None,
    )
