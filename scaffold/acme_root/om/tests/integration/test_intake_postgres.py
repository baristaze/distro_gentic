"""Intake and automations over Postgres: a failing check on a session's
pull request wakes it as data, and fires an automation whose run starts a
session held to its share of the cost cap, recorded once."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from contracts.intake import wired
from contracts.loops import reply, said

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.agents.types.run import RunEnd
from acme.om.automations.types.automation import (
    Action,
    ActionKind,
    Automation,
    Firing,
    Limits,
    RunStatus,
    Trigger,
    TriggerKind,
)
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, RequestContext, Role, TenantContext
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
from acme.om.steps.rules import message_step
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings

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
