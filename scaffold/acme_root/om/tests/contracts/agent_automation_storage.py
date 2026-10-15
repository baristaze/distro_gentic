"""The agent automations storage contract: a tenant's agent automations and the record
of every firing, with the limits asked inside the write that records a
run. The cases named in `CROSS_TENANT_CASES` are the tenant fence's
evidence: each one presents another tenant's identifier and asserts that
nothing is found and nothing changes."""

from collections import Counter
from uuid import UUID

from acme.om.agent_automations.storage import AgentAutomationStorageInterface
from acme.om.agent_automations.types.agent_automation import (
    Action,
    ActionKind,
    AgentAutomation,
    AgentAutomationPrincipal,
    AgentAutomationRun,
    Limits,
    Refusal,
    RunOutcome,
    RunStatus,
    Trigger,
    TriggerKind,
)
from acme.om.base import new_id, utcnow
from acme.om.context import Role

from contracts.racing import race

INTERFACE = AgentAutomationStorageInterface
"""The storage interface whose cross-tenant cases this suite holds."""

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_agent_automation",
        "read_agent_automation",
        "read_agent_automations",
        "write_agent_automation",
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
"""Every method of `AgentAutomationStorageInterface` that takes a tenant has a
case in this module that presents another tenant's."""

LIMITS = Limits(cost_cap_micros=3_000_000, run_cap_micros=1_000_000, rate=10, concurrency=10)


def make_agent_automation(limits: Limits = LIMITS) -> AgentAutomation:
    now = utcnow()
    actor = new_id()
    return AgentAutomation(
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


def make_run(agent_automation_id: UUID, agent_session_id: UUID | None = None) -> AgentAutomationRun:
    return AgentAutomationRun(
        id=new_id(),
        created_at=utcnow(),
        agent_automation_id=agent_automation_id,
        event_id=new_id(),
        status=RunStatus.REFUSED,
        refusal=Refusal.HOP_LIMIT,
        hop=1,
        agent_session_id=agent_session_id,
    )


def make_principal(role: Role) -> AgentAutomationPrincipal:
    return AgentAutomationPrincipal(
        id=new_id(), created_at=utcnow(), role=role, granted_by=new_id()
    )


class AgentAutomationStorageContract:
    async def test_an_agent_automation_reads_back_whole(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        agent_automation = make_agent_automation()
        assert await storage.create_agent_automation(org, agent_automation, ())
        assert not await storage.create_agent_automation(org, agent_automation, ())
        assert await storage.read_agent_automation(org, agent_automation.id) == agent_automation
        assert await storage.read_agent_automations(org, None, 10) == [agent_automation]
        assert await storage.read_agent_automations(org, agent_automation.id, 10) == []

    async def test_admit_starts_runs_until_the_cost_cap_and_reserves_each_runs_cap(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        agent_automation = make_agent_automation()
        await storage.create_agent_automation(org, agent_automation, ())
        now = utcnow()
        landed = [
            await storage.admit(org, make_run(agent_automation.id), LIMITS, now) for _ in range(4)
        ]
        assert [r.status for r in landed] == [RunStatus.STARTED] * 3 + [RunStatus.REFUSED]
        assert [r.reserved_micros for r in landed] == [1_000_000] * 3 + [0]
        assert landed[3].refusal is Refusal.COST_CAP

    async def test_admissions_at_once_never_reserve_past_the_cap(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        agent_automation = make_agent_automation()
        await storage.create_agent_automation(org, agent_automation, ())
        now = utcnow()
        run = await race(
            *(storage.admit(org, make_run(agent_automation.id), LIMITS, now) for _ in range(6))
        )
        # Overlapped (Postgres), the agent automation's row orders the admissions;
        # not (memory), each one is asked against what the one before left.
        started = [r for r in run.outcomes if r.status is RunStatus.STARTED]
        assert len(started) == 3, run.summary()
        assert sum(r.reserved_micros for r in started) <= LIMITS.cost_cap_micros

    async def test_a_queued_run_is_admitted_again_and_a_started_one_answers_as_stored(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        limits = LIMITS.model_copy(update={"concurrency": 1, "queue": True})
        agent_automation = make_agent_automation(limits)
        await storage.create_agent_automation(org, agent_automation, ())
        now = utcnow()
        first = await storage.admit(org, make_run(agent_automation.id), limits, now)
        queued = await storage.admit(org, make_run(agent_automation.id), limits, now)
        assert (queued.status, queued.refusal) == (RunStatus.QUEUED, Refusal.CONCURRENCY)
        assert await storage.read_queued_runs(org, agent_automation.id, 10) == [queued]
        assert await storage.admit(org, first, limits, now) == first
        await storage.write_run(org, first.model_copy(update={"closed_at": utcnow()}))
        again = await storage.admit(org, queued, limits, now)
        assert again.id == queued.id and again.status is RunStatus.STARTED
        assert await storage.read_queued_runs(org, agent_automation.id, 10) == []

    async def test_a_full_queue_refuses_a_firing_and_keeps_the_runs_that_wait(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        limits = LIMITS.model_copy(update={"rate": 1, "queue": True, "queue_depth": 2})
        agent_automation = make_agent_automation(limits)
        await storage.create_agent_automation(org, agent_automation, ())
        now = utcnow()
        landed = [
            await storage.admit(org, make_run(agent_automation.id), limits, now) for _ in range(4)
        ]
        assert [(r.status, r.refusal) for r in landed] == [
            (RunStatus.STARTED, None),
            (RunStatus.QUEUED, Refusal.RATE),
            (RunStatus.QUEUED, Refusal.RATE),
            (RunStatus.REFUSED, Refusal.QUEUE_FULL),
        ]
        again = await storage.admit(org, landed[1], limits, now)
        assert (again.status, again.refusal) == (RunStatus.QUEUED, Refusal.RATE)
        waiting = await storage.read_queued_runs(org, agent_automation.id, 10)
        assert {r.id for r in waiting} == {landed[1].id, landed[2].id}

    async def test_firings_at_once_never_queue_past_the_depth(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        limits = LIMITS.model_copy(update={"rate": 1, "queue": True, "queue_depth": 2})
        agent_automation = make_agent_automation(limits)
        await storage.create_agent_automation(org, agent_automation, ())
        now = utcnow()
        run = await race(
            *(storage.admit(org, make_run(agent_automation.id), limits, now) for _ in range(6))
        )
        # The depth is read in the admission's own write: overlapped
        # (Postgres), the agent automation's row orders them; not (memory), each
        # is asked against what the one before left.
        landed = Counter((r.status, r.refusal) for r in run.outcomes)
        assert landed == {
            (RunStatus.STARTED, None): 1,
            (RunStatus.QUEUED, Refusal.RATE): 2,
            (RunStatus.REFUSED, Refusal.QUEUE_FULL): 3,
        }, run.summary()
        assert len(await storage.read_queued_runs(org, agent_automation.id, 10)) == 2

    async def test_runs_read_newest_first_open_ones_and_a_sessions(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        agent_automation = make_agent_automation()
        await storage.create_agent_automation(org, agent_automation, ())
        now = utcnow()
        agent_session_id = new_id()
        started = await storage.admit(org, make_run(agent_automation.id), LIMITS, now)
        with_session = started.model_copy(
            update={"agent_session_id": agent_session_id, "opened": True}
        )
        await storage.write_run(org, with_session)
        refused = await storage.create_run(org, make_run(agent_automation.id))
        assert await storage.create_run(org, refused) == refused
        assert [r.id for r in await storage.read_runs(org, agent_automation.id, 10)] == [
            refused.id,
            started.id,
        ]
        assert await storage.read_open_runs(org, agent_automation.id, 10) == [with_session]
        assert await storage.read_session_run(org, agent_session_id) == with_session
        assert await storage.read_session_run(org, new_id()) is None

    async def test_an_agent_automation_is_written_in_place_and_never_brought_back(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        agent_automation = make_agent_automation()
        await storage.create_agent_automation(org, agent_automation, ())
        edited = agent_automation.model_copy(update={"name": "edited", "enabled": False})
        assert await storage.write_agent_automation(org, edited, ())
        assert await storage.read_agent_automation(org, agent_automation.id) == edited
        assert not await storage.write_agent_automation(org, make_agent_automation(), ())

    async def test_write_agent_automation_of_another_tenant_changes_nothing(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        agent_automation = make_agent_automation()
        await storage.create_agent_automation(org_a, agent_automation, ())
        taken = agent_automation.model_copy(update={"name": "taken"})
        assert not await storage.write_agent_automation(org_b, taken, ())
        assert await storage.read_agent_automation(org_a, agent_automation.id) == agent_automation
        assert await storage.read_agent_automation(org_b, agent_automation.id) is None

    async def test_create_agent_automation_in_another_tenant_is_not_read_here(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        agent_automation = make_agent_automation()
        await storage.create_agent_automation(org_a, agent_automation, ())
        assert not await storage.create_agent_automation(org_b, agent_automation, ())
        assert await storage.read_agent_automation(org_b, agent_automation.id) is None

    async def test_read_agent_automation_of_another_tenant_finds_nothing(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        agent_automation = make_agent_automation()
        await storage.create_agent_automation(new_id(), agent_automation, ())
        assert await storage.read_agent_automation(new_id(), agent_automation.id) is None

    async def test_read_agent_automations_of_another_tenant_finds_nothing(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        await storage.create_agent_automation(new_id(), make_agent_automation(), ())
        assert await storage.read_agent_automations(new_id(), None, 10) == []

    async def test_admit_counts_no_other_tenants_runs(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        agent_automation = make_agent_automation()
        await storage.create_agent_automation(org_a, agent_automation, ())
        await storage.create_agent_automation(org_b, agent_automation, ())
        now = utcnow()
        for _ in range(3):
            await storage.admit(org_a, make_run(agent_automation.id), LIMITS, now)
        theirs = await storage.admit(org_b, make_run(agent_automation.id), LIMITS, now)
        assert theirs.status is RunStatus.STARTED

    async def test_create_run_of_another_tenant_is_not_read_here(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        run = make_run(new_id())
        await storage.create_run(new_id(), run)
        assert await storage.read_runs(new_id(), run.agent_automation_id, 10) == []

    async def test_write_run_of_another_tenant_changes_nothing(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        run = await storage.create_run(org, make_run(new_id()))
        await storage.write_run(new_id(), run.model_copy(update={"hop": 3}))
        assert await storage.read_runs(org, run.agent_automation_id, 10) == [run]

    async def test_read_runs_of_another_tenant_finds_nothing(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        run = await storage.create_run(new_id(), make_run(new_id()))
        assert await storage.read_runs(new_id(), run.agent_automation_id, 10) == []

    async def test_read_open_runs_of_another_tenant_finds_nothing(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        agent_automation = make_agent_automation()
        await storage.create_agent_automation(org, agent_automation, ())
        await storage.admit(org, make_run(agent_automation.id), LIMITS, utcnow())
        assert await storage.read_open_runs(new_id(), agent_automation.id, 10) == []

    async def test_read_queued_runs_of_another_tenant_finds_nothing(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        limits = LIMITS.model_copy(update={"rate": 1, "queue": True})
        agent_automation = make_agent_automation(limits)
        await storage.create_agent_automation(org, agent_automation, ())
        now = utcnow()
        await storage.admit(org, make_run(agent_automation.id), limits, now)
        await storage.admit(org, make_run(agent_automation.id), limits, now)
        assert len(await storage.read_queued_runs(org, agent_automation.id, 10)) == 1
        assert await storage.read_queued_runs(new_id(), agent_automation.id, 10) == []

    async def test_read_session_run_of_another_tenant_finds_nothing(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        agent_automation = make_agent_automation()
        await storage.create_agent_automation(org, agent_automation, ())
        run = await storage.admit(org, make_run(agent_automation.id), LIMITS, utcnow())
        agent_session_id = new_id()
        await storage.write_run(org, run.model_copy(update={"agent_session_id": agent_session_id}))
        assert await storage.read_session_run(new_id(), agent_session_id) is None

    async def test_a_run_reads_back_by_its_id_in_its_tenant_alone(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        agent_automation = make_agent_automation()
        await storage.create_agent_automation(org, agent_automation, ())
        run = await storage.create_run(org, make_run(agent_automation.id))
        assert await storage.read_run(org, run.id) == run
        assert await storage.read_run(new_id(), run.id) is None

    async def test_a_products_action_reads_back_whole_with_the_work_its_run_ended(
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org = new_id()
        agent_automation = make_agent_automation().model_copy(
            update={"action": Action(kind="run_job", params={"steps": 2, "on": ["a", "b"]})}
        )
        assert await storage.create_agent_automation(org, agent_automation, ())
        assert await storage.read_agent_automation(org, agent_automation.id) == agent_automation
        run = await storage.create_run(org, make_run(agent_automation.id))
        ended = run.model_copy(
            update={"work_id": new_id(), "outcome": RunOutcome.FAILED, "closed_at": utcnow()}
        )
        await storage.write_run(org, ended)
        assert await storage.read_run(org, run.id) == ended

    async def test_one_principal_a_tenant_whose_grant_keeps_its_id(
        self, storage: AgentAutomationStorageInterface
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
        self, storage: AgentAutomationStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        agent_automation = make_agent_automation()
        await storage.create_agent_automation(org_a, agent_automation, ())
        await storage.create_run(org_a, make_run(agent_automation.id))
        await storage.write_principal(org_a, make_principal(Role.MEMBER))
        kept = make_agent_automation()
        await storage.create_agent_automation(org_b, kept, ())
        held = await storage.write_principal(org_b, make_principal(Role.MEMBER))
        assert await storage.purge_tenant(org_a, 10) == 3
        assert await storage.read_principal(org_a) is None
        assert await storage.read_principal(org_b) == held
        assert await storage.purge_tenant(org_a, 10) == 0
        assert await storage.read_agent_automation(org_b, kept.id) == kept
