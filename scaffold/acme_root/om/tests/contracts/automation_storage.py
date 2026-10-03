"""The automations storage contract: a tenant's automations and the record
of every firing, with the limits asked inside the write that records a
run. The cases named in `CROSS_TENANT_CASES` are the tenant fence's
evidence: each one presents another tenant's identifier and asserts that
nothing is found and nothing changes."""

from uuid import UUID

from acme.om.automations.storage import AutomationStorageInterface
from acme.om.automations.types.automation import (
    Action,
    ActionKind,
    Automation,
    AutomationPrincipal,
    AutomationRun,
    Limits,
    Refusal,
    RunStatus,
    Trigger,
    TriggerKind,
)
from acme.om.base import new_id, utcnow
from acme.om.context import Role
from contracts.racing import race

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_automation",
        "read_automation",
        "read_automations",
        "admit",
        "create_run",
        "write_run",
        "read_runs",
        "read_open_runs",
        "read_queued_runs",
        "read_session_run",
        "read_run",
        "write_principal",
        "read_principal",
        "purge_tenant",
    }
)
"""Every method of `AutomationStorageInterface` that takes a tenant has a
case in this module that presents another tenant's."""

LIMITS = Limits(cost_cap_micros=3_000_000, run_cap_micros=1_000_000, rate=10, concurrency=10)


def make_automation(limits: Limits = LIMITS) -> Automation:
    now = utcnow()
    actor = new_id()
    return Automation(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        name="triage failing checks",
        trigger=Trigger(kind=TriggerKind.EVENT, arrivals=("check",), effects=("wake_as_data",)),
        action=Action(
            kind=ActionKind.START_SESSION,
            brief="Find why the check failed, and say so on the pull request.",
            agent_kind="steady",
            title="a failing check",
        ),
        limits=limits,
    )


def make_run(automation_id: UUID, session_id: UUID | None = None) -> AutomationRun:
    return AutomationRun(
        id=new_id(),
        created_at=utcnow(),
        automation_id=automation_id,
        event_id=new_id(),
        status=RunStatus.REFUSED,
        refusal=Refusal.HOP_LIMIT,
        hop=1,
        session_id=session_id,
    )


def make_principal(role: Role) -> AutomationPrincipal:
    return AutomationPrincipal(id=new_id(), created_at=utcnow(), role=role, granted_by=new_id())


class AutomationStorageContract:
    async def test_an_automation_reads_back_whole(
        self, storage: AutomationStorageInterface
    ) -> None:
        org = new_id()
        automation = make_automation()
        assert await storage.create_automation(org, automation, ())
        assert not await storage.create_automation(org, automation, ())
        assert await storage.read_automation(org, automation.id) == automation
        assert await storage.read_automations(org, None, 10) == [automation]
        assert await storage.read_automations(org, automation.id, 10) == []

    async def test_admit_starts_runs_until_the_cost_cap_and_reserves_each_runs_cap(
        self, storage: AutomationStorageInterface
    ) -> None:
        org = new_id()
        automation = make_automation()
        await storage.create_automation(org, automation, ())
        now = utcnow()
        landed = [await storage.admit(org, make_run(automation.id), LIMITS, now) for _ in range(4)]
        assert [r.status for r in landed] == [RunStatus.STARTED] * 3 + [RunStatus.REFUSED]
        assert [r.reserved_micros for r in landed] == [1_000_000] * 3 + [0]
        assert landed[3].refusal is Refusal.COST_CAP

    async def test_admissions_at_once_never_reserve_past_the_cap(
        self, storage: AutomationStorageInterface
    ) -> None:
        org = new_id()
        automation = make_automation()
        await storage.create_automation(org, automation, ())
        now = utcnow()
        run = await race(
            *(storage.admit(org, make_run(automation.id), LIMITS, now) for _ in range(6))
        )
        # Overlapped (Postgres), the automation's row orders the admissions;
        # not (memory), each one is asked against what the one before left.
        started = [r for r in run.outcomes if r.status is RunStatus.STARTED]
        assert len(started) == 3, run.summary()
        assert sum(r.reserved_micros for r in started) <= LIMITS.cost_cap_micros

    async def test_a_queued_run_is_admitted_again_and_a_started_one_answers_as_stored(
        self, storage: AutomationStorageInterface
    ) -> None:
        org = new_id()
        limits = LIMITS.model_copy(update={"concurrency": 1, "queue": True})
        automation = make_automation(limits)
        await storage.create_automation(org, automation, ())
        now = utcnow()
        first = await storage.admit(org, make_run(automation.id), limits, now)
        queued = await storage.admit(org, make_run(automation.id), limits, now)
        assert (queued.status, queued.refusal) == (RunStatus.QUEUED, Refusal.CONCURRENCY)
        assert await storage.read_queued_runs(org, automation.id, 10) == [queued]
        assert await storage.admit(org, first, limits, now) == first
        await storage.write_run(org, first.model_copy(update={"closed_at": utcnow()}))
        again = await storage.admit(org, queued, limits, now)
        assert again.id == queued.id and again.status is RunStatus.STARTED
        assert await storage.read_queued_runs(org, automation.id, 10) == []

    async def test_runs_read_newest_first_open_ones_and_a_sessions(
        self, storage: AutomationStorageInterface
    ) -> None:
        org = new_id()
        automation = make_automation()
        await storage.create_automation(org, automation, ())
        now = utcnow()
        session_id = new_id()
        started = await storage.admit(org, make_run(automation.id), LIMITS, now)
        with_session = started.model_copy(update={"session_id": session_id, "opened": True})
        await storage.write_run(org, with_session)
        refused = await storage.create_run(org, make_run(automation.id))
        assert await storage.create_run(org, refused) == refused
        assert [r.id for r in await storage.read_runs(org, automation.id, 10)] == [
            refused.id,
            started.id,
        ]
        assert await storage.read_open_runs(org, automation.id, 10) == [with_session]
        assert await storage.read_session_run(org, session_id) == with_session
        assert await storage.read_session_run(org, new_id()) is None

    async def test_create_automation_in_another_tenant_is_not_read_here(
        self, storage: AutomationStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        automation = make_automation()
        await storage.create_automation(org_a, automation, ())
        assert not await storage.create_automation(org_b, automation, ())
        assert await storage.read_automation(org_b, automation.id) is None

    async def test_read_automation_of_another_tenant_finds_nothing(
        self, storage: AutomationStorageInterface
    ) -> None:
        automation = make_automation()
        await storage.create_automation(new_id(), automation, ())
        assert await storage.read_automation(new_id(), automation.id) is None

    async def test_read_automations_of_another_tenant_finds_nothing(
        self, storage: AutomationStorageInterface
    ) -> None:
        await storage.create_automation(new_id(), make_automation(), ())
        assert await storage.read_automations(new_id(), None, 10) == []

    async def test_admit_counts_no_other_tenants_runs(
        self, storage: AutomationStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        automation = make_automation()
        await storage.create_automation(org_a, automation, ())
        await storage.create_automation(org_b, automation, ())
        now = utcnow()
        for _ in range(3):
            await storage.admit(org_a, make_run(automation.id), LIMITS, now)
        theirs = await storage.admit(org_b, make_run(automation.id), LIMITS, now)
        assert theirs.status is RunStatus.STARTED

    async def test_create_run_of_another_tenant_is_not_read_here(
        self, storage: AutomationStorageInterface
    ) -> None:
        run = make_run(new_id())
        await storage.create_run(new_id(), run)
        assert await storage.read_runs(new_id(), run.automation_id, 10) == []

    async def test_write_run_of_another_tenant_changes_nothing(
        self, storage: AutomationStorageInterface
    ) -> None:
        org = new_id()
        run = await storage.create_run(org, make_run(new_id()))
        await storage.write_run(new_id(), run.model_copy(update={"hop": 3}))
        assert await storage.read_runs(org, run.automation_id, 10) == [run]

    async def test_read_runs_of_another_tenant_finds_nothing(
        self, storage: AutomationStorageInterface
    ) -> None:
        run = await storage.create_run(new_id(), make_run(new_id()))
        assert await storage.read_runs(new_id(), run.automation_id, 10) == []

    async def test_read_open_runs_of_another_tenant_finds_nothing(
        self, storage: AutomationStorageInterface
    ) -> None:
        org = new_id()
        automation = make_automation()
        await storage.create_automation(org, automation, ())
        await storage.admit(org, make_run(automation.id), LIMITS, utcnow())
        assert await storage.read_open_runs(new_id(), automation.id, 10) == []

    async def test_read_queued_runs_of_another_tenant_finds_nothing(
        self, storage: AutomationStorageInterface
    ) -> None:
        org = new_id()
        limits = LIMITS.model_copy(update={"rate": 1, "queue": True})
        automation = make_automation(limits)
        await storage.create_automation(org, automation, ())
        now = utcnow()
        await storage.admit(org, make_run(automation.id), limits, now)
        await storage.admit(org, make_run(automation.id), limits, now)
        assert len(await storage.read_queued_runs(org, automation.id, 10)) == 1
        assert await storage.read_queued_runs(new_id(), automation.id, 10) == []

    async def test_read_session_run_of_another_tenant_finds_nothing(
        self, storage: AutomationStorageInterface
    ) -> None:
        org = new_id()
        automation = make_automation()
        await storage.create_automation(org, automation, ())
        run = await storage.admit(org, make_run(automation.id), LIMITS, utcnow())
        session_id = new_id()
        await storage.write_run(org, run.model_copy(update={"session_id": session_id}))
        assert await storage.read_session_run(new_id(), session_id) is None

    async def test_a_run_reads_back_by_its_id_in_its_tenant_alone(
        self, storage: AutomationStorageInterface
    ) -> None:
        org = new_id()
        automation = make_automation()
        await storage.create_automation(org, automation, ())
        run = await storage.create_run(org, make_run(automation.id))
        assert await storage.read_run(org, run.id) == run
        assert await storage.read_run(new_id(), run.id) is None

    async def test_one_principal_a_tenant_whose_grant_keeps_its_id(
        self, storage: AutomationStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        first = make_principal(Role.MEMBER)
        assert await storage.write_principal(org, first) == first
        again = await storage.write_principal(org, make_principal(Role.VIEWER))
        assert (again.id, again.role) == (first.id, Role.VIEWER)
        assert await storage.read_principal(org) == again
        assert await storage.read_principal(other) is None
        theirs = await storage.write_principal(other, make_principal(Role.MEMBER))
        assert theirs.id != first.id and await storage.read_principal(org) == again

    async def test_purge_tenant_takes_its_rows_and_no_other_tenants(
        self, storage: AutomationStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        automation = make_automation()
        await storage.create_automation(org_a, automation, ())
        await storage.create_run(org_a, make_run(automation.id))
        await storage.write_principal(org_a, make_principal(Role.MEMBER))
        kept = make_automation()
        await storage.create_automation(org_b, kept, ())
        held = await storage.write_principal(org_b, make_principal(Role.MEMBER))
        assert await storage.purge_tenant(org_a, 10) == 3
        assert await storage.read_principal(org_a) is None
        assert await storage.read_principal(org_b) == held
        assert await storage.purge_tenant(org_a, 10) == 0
        assert await storage.read_automation(org_b, kept.id) == kept
