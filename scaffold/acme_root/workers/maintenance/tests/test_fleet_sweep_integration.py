"""The platform's duties on the sweep, over Postgres, as the worker runs
them: its container built from its settings, its loop's pass. A loop whose
runner died is requeued, and its next run takes a new writer epoch. A hold
nobody settled settles at the bill the provider gives, else whole, never
below what the provider billed, and is released only on its proof. A
session pending with no loop has its run asked for again, once, and one
whose run holds its loop is never asked for."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from worker_support import request

from acme.om.agent_sessions.rules import resumed_step
from acme.om.agent_sessions.types.agent_session import AgentSession, SessionStatus
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import derived_id, new_id, utcnow
from acme.om.billing.impl.sweep import HoldSweepImpl, HoldSweepOptions
from acme.om.billing.sweep import ProviderBillsInterface
from acme.om.budgets.types.amount import Amount, Spend
from acme.om.budgets.types.budget import BudgetScope, BudgetScopeKind
from acme.om.budgets.types.hold import (
    Bill,
    Billed,
    BillUnknown,
    Hold,
    HoldLine,
    NotBilled,
    NotBilledProof,
    Settlement,
)
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    OperatorContext,
    OperatorRole,
    TenantContext,
)
from acme.om.exceptions import StaleWriter
from acme.om.placement.rules import own_lane
from acme.om.steps.types.content import Content, TextBlock
from acme.om.steps.types.header import InputHeader, ModelRequestHeader
from acme.om.steps.types.step import Actor, Origin, Step, StepType
from acme.om.tenancy.rules import operator_permissions_of
from acme.om.work.types.work_item import LoopPayload, WorkItem, WorkKind, WorkStatus
from acme.workers.maintenance.container import WorkerContainer
from acme.workers.maintenance.main import build_loop
from acme.workers.maintenance.sessions import StalledOptions, StalledSessionsSweep
from acme.workers.maintenance.settings import MaintenanceSettings

pytestmark = pytest.mark.integration


@pytest.fixture
async def container(tmp_path: Path) -> AsyncIterator[WorkerContainer]:
    settings = MaintenanceSettings(
        cache_backend="memory",
        topics_backend="memory",
        buckets_backend="local",
        buckets_root=tmp_path / "buckets",
        queues_backend="memory",
        secrets_backend="local",
        keys_backend="memory",
        sentry_dsn=None,
        otel_endpoint=None,
        worker_id="fleet-integration",
    )
    settings.refuse_remote()
    built = WorkerContainer.build(settings)
    yield built
    await built.close()


async def an_owner(container: WorkerContainer) -> TenantContext:
    tail = new_id().hex[-8:]
    owner, _ = await container.managers.tenancy.bootstrap(
        request(), "Pump", f"pump-{tail}", f"pump-{tail}@example.test", "Pat"
    )
    return owner


def a_session() -> AgentSession:
    now, by, session_id = utcnow(), new_id(), new_id()
    return AgentSession(
        id=session_id,
        created_at=now,
        updated_at=now,
        created_by=by,
        updated_by=by,
        title="the pump's pressure log",
        kind="delivery",
        kind_version=1,
        root_id=session_id,
    )


def a_message(session_id: UUID) -> Step:
    step_id = new_id()
    return Step(
        id=step_id,
        created_at=utcnow(),
        session_id=session_id,
        loop_id=step_id,
        type=StepType.MESSAGE,
        actor=Actor.PERSON,
        origin=Origin.PORTAL,
        header=InputHeader(principal=Principal(kind=PrincipalKind.PERSON, id=new_id())),
        content=Content(blocks=(TextBlock(text="why did the pressure spike at 14:02?"),)),
    )


# A loop whose runner died.


async def test_an_expired_loop_is_requeued_and_its_next_run_takes_a_new_epoch(
    container: WorkerContainer,
) -> None:
    managers = container.managers
    owner = await an_owner(container)
    session = await managers.agent_sessions.create_session(owner, a_session())
    (message,) = await managers.steps.append_inputs(owner, session.id, [a_message(session.id)])
    # The loop's item on a lane of this test's own, claimed by a runner that
    # then dies: its lease runs out with nobody to renew it.
    lane, now = f"loop:fleet-{new_id().hex[-8:]}", utcnow()
    item = WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=owner.user_id,
        updated_by=owner.user_id,
        kind=WorkKind.LOOP,
        target_id=session.id,
        idempotency_key=new_id(),
        request_id=new_id(),
        payload=LoopPayload().model_dump(mode="json"),
        lane=lane,
        available_at=now,
    )
    await container.storage.get_work_storage().create_item(owner.org_id, item)
    claimed = await managers.work.claim(
        request(), lane, [WorkKind.LOOP], "runner-that-dies", timedelta(milliseconds=1)
    )
    assert claimed is not None and claimed[1].id == item.id
    dead_ctx, _ = claimed
    lost = await managers.steps.begin_run(dead_ctx, session.id)
    await asyncio.sleep(0.05)

    await build_loop(container)._sweep_once()  # pyright: ignore[reportPrivateUsage]

    again = await managers.work.claim(
        request(), lane, [WorkKind.LOOP], "runner-next", timedelta(minutes=1)
    )
    assert again is not None, "the sweep put the loop back in its lane"
    ctx, requeued = again
    assert (requeued.id, requeued.status) == (item.id, WorkStatus.CLAIMED)
    epoch = await managers.steps.begin_run(ctx, session.id)
    assert epoch > lost
    # The run that died writes nothing more.
    with pytest.raises(StaleWriter):
        await managers.steps.append_steps(
            dead_ctx, session.id, lost, [resumed_step(new_id(), session.id, message.id, utcnow())]
        )


# A hold nobody settled.

DAY = datetime(2026, 10, 2, tzinfo=UTC)


def a_hold(org_line: HoldLine, opened: datetime, cost: int = 600) -> Hold:
    return Hold(
        id=new_id(),
        created_at=opened,
        spender_id=new_id(),
        session_id=new_id(),
        purpose="main",
        exposure=Spend(cost_micros=cost, tokens=100),
        lines=(org_line,),
    )


def a_line() -> HoldLine:
    return HoldLine(
        budget_id=new_id(),
        scope=BudgetScope(kind=BudgetScopeKind.SESSION, key="s-1"),
        window_start=DAY,
        resets_at=DAY + timedelta(days=1),
        amount=Amount(cost_micros=1_000_000),
    )


async def settlement(container: WorkerContainer, org_id: UUID, hold: Hold) -> Settlement | None:
    return await container.storage.get_ledger_storage().read_settlement(org_id, hold.id)


async def test_a_hold_nobody_settled_settles_whole_once_its_call_is_past(
    container: WorkerContainer,
) -> None:
    """A hold opened two hours ago that no settlement closed settles whole:
    its call was sent, so it is usually billed, and the worst case it holds
    is never below the bill. A hold its run settled keeps that settlement,
    and a hold whose call may still stream is left open."""
    owner = await an_owner(container)
    ledger, now = container.storage.get_ledger_storage(), utcnow()
    line = a_line()
    stale = a_hold(line, now - timedelta(hours=2))
    settled = a_hold(line, now - timedelta(hours=2))
    young = a_hold(line, now - timedelta(minutes=10))
    for hold in (stale, settled, young):
        assert await ledger.open_hold(owner.org_id, hold) is None
    usage = Billed(usage=Spend(cost_micros=250, tokens=40))
    first = await container.managers.budget_gate.settle(owner, settled.id, usage)

    await build_loop(container)._sweep_once()  # pyright: ignore[reportPrivateUsage]

    whole = await settlement(container, owner.org_id, stale)
    assert whole is not None and isinstance(whole.bill, BillUnknown)
    assert whole.spent == stale.exposure
    assert await settlement(container, owner.org_id, settled) == first
    assert await settlement(container, owner.org_id, young) is None
    tally = await ledger.read_tally(owner.org_id, line.budget_id, line.window_start)
    assert tally is not None
    # The young hold still reserves its worst case; the others spent theirs.
    assert (tally.held_cost_micros, tally.spent_cost_micros) == (600, 600 + 250)


class Bills(ProviderBillsInterface):
    """The provider's answer for each hold, as a test sets it."""

    def __init__(self, answers: dict[UUID, Bill | Exception]) -> None:
        self._answers = answers

    async def retrieve(self, org_id: UUID, hold: Hold) -> Bill | None:
        answer = self._answers.get(hold.id)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def describe(self) -> str:
        return "provider_bills=test"


async def test_a_hold_settles_at_the_providers_bill_and_is_released_only_on_its_proof(
    container: WorkerContainer,
) -> None:
    """The bill the provider gives settles the hold: its usage, past the
    hold too, never less; a release only with the proof that nothing was
    billed. A provider that cannot answer leaves the hold whole."""
    owner = await an_owner(container)
    ledger, now = container.storage.get_ledger_storage(), utcnow()
    line = a_line()
    billed, over, released, unanswered = (a_hold(line, now - timedelta(hours=2)) for _ in range(4))
    for hold in (billed, over, released, unanswered):
        assert await ledger.open_hold(owner.org_id, hold) is None
    proof = NotBilled(proof=NotBilledProof.REFUSED_BEFORE_PROCESSING)
    sweep = HoldSweepImpl(
        ledger,
        container.managers.budget_gate,
        container.managers.tenancy,
        Bills(
            {
                billed.id: Billed(usage=Spend(cost_micros=420, tokens=60)),
                over.id: Billed(usage=Spend(cost_micros=900, tokens=60)),
                released.id: proof,
                unanswered.id: ConnectionError("the provider's usage API is down"),
            }
        ),
        HoldSweepOptions(),
    )

    assert await sweep.settle_open(request()) >= 4

    spent = {
        hold.id: found.spent.cost_micros
        for hold in (billed, over, released, unanswered)
        if (found := await settlement(container, owner.org_id, hold)) is not None
    }
    assert spent == {billed.id: 420, over.id: 900, released.id: 0, unanswered.id: 600}
    passed = await settlement(container, owner.org_id, over)
    assert passed is not None and passed.overshoot == Spend(cost_micros=300, tokens=0)


# A session pending with no loop.


def an_operator() -> OperatorContext:
    return OperatorContext(
        request_id=new_id(),
        app=AppContext(type=AppType.CLI, version="ops@test"),
        identity_id=new_id(),
        email="root@example.test",
        credential_kind=CredentialKind.LOGIN,
        credential_id=new_id(),
        permissions=operator_permissions_of(OperatorRole.WRITE),
    )


async def an_owner_on_its_own_lane(container: WorkerContainer) -> TenantContext:
    """A tenant whose loops land in a lane of its own, so a claim there takes
    this test's loops and no other's."""
    owner = await an_owner(container)
    await container.managers.placement_operator.set_share(
        an_operator(), owner.org_id, plan_tier="standard", own_lane=True, concurrency=8
    )
    return owner


async def its_loop(
    container: WorkerContainer, owner: TenantContext
) -> tuple[TenantContext, WorkItem]:
    """The tenant's next loop, claimed by a runner that holds it for an hour."""
    claimed = await container.managers.work.claim(
        request(), own_lane(owner.org_id), [WorkKind.LOOP], "runner", timedelta(hours=1)
    )
    assert claimed is not None
    return claimed


def a_sweep(container: WorkerContainer, at: datetime) -> StalledSessionsSweep:
    managers = container.managers
    return StalledSessionsSweep(
        managers.agent_sessions,
        managers.steps,
        managers.work,
        managers.tenancy,
        StalledOptions(),
        clock=lambda: at,
    )


def a_model_request(message: Step, at: datetime) -> Step:
    person = Principal(kind=PrincipalKind.PERSON, id=new_id())
    return Step(
        id=new_id(),
        created_at=at,
        session_id=message.session_id,
        loop_id=message.loop_id,
        type=StepType.MODEL_REQUEST,
        actor=Actor.ENGINE,
        origin=Origin.ENGINE,
        refs=(message.id,),
        header=ModelRequestHeader(
            role="main",
            spender=person,
            speaker=person,
            fill="anthropic/claude-sonnet-5-5",
            fill_set_version=1,
            left_edge=1,
            prompt_hash="k:prompt",
        ),
    )


async def test_a_session_pending_with_no_loop_has_its_run_asked_for_once(
    container: WorkerContainer,
) -> None:
    """A session pending past twenty minutes whose loop failed for good is
    one no run holds: the sweep asks for its run, as the person who made the
    session, keyed on the write that left it pending, so a second pass asks
    nothing more. A session pending for less, or idle, is left alone."""
    managers = container.managers
    owner = await an_owner_on_its_own_lane(container)
    stuck = await managers.agent_sessions.create_session(owner, a_session())
    idle = await managers.agent_sessions.create_session(owner, a_session())
    _, stuck = await managers.agent_sessions.receive(owner, stuck.id, [a_message(stuck.id)])
    assert stuck.status is SessionStatus.PENDING
    ctx, loop = await its_loop(container, owner)
    assert loop.target_id == stuck.id
    await managers.work.fail_for_good(ctx, loop, "the runner refused it")

    work = container.storage.get_work_storage()
    key = derived_id(stuck.id, stuck.updated_at, f"stalled:{stuck.version}")
    await a_sweep(container, utcnow())(request())
    assert await work.read_item_by_key(owner.org_id, key) is None, "not stalled yet"

    later = utcnow() + StalledOptions().stall_after + timedelta(minutes=1)
    assert await a_sweep(container, later)(request()) >= 1
    asked = await work.read_item_by_key(owner.org_id, key)
    assert asked is not None
    assert (asked.kind, asked.target_id, asked.created_by) == (
        WorkKind.LOOP,
        stuck.id,
        stuck.created_by,
    )
    idle_key = derived_id(idle.id, idle.updated_at, f"stalled:{idle.version}")
    assert await work.read_item_by_key(owner.org_id, idle_key) is None, "an idle session waits"
    # A second pass, of this worker or another, asks for nothing more.
    await a_sweep(container, later)(request())
    assert await work.read_item_by_key(owner.org_id, key) == asked


async def test_a_session_whose_run_holds_its_loop_is_not_asked_for_again(
    container: WorkerContainer,
) -> None:
    """A run never writes its session's row while it drives a loop, so a
    session pending past twenty minutes may be one a run still holds: its
    loop claimed, its last step a minute old. The sweep asks nothing for it,
    since the run it asked for would take the next epoch and fence the live
    one. Its last step alone holds it too, until it is as old."""
    managers = container.managers
    owner = await an_owner_on_its_own_lane(container)
    session = await managers.agent_sessions.create_session(owner, a_session())
    (message,), session = await managers.agent_sessions.receive(
        owner, session.id, [a_message(session.id)]
    )
    # The run as a runner drives it: its loop claimed, its epoch, the
    # projection at its start, then a model request 21 minutes after the input.
    ctx, loop = await its_loop(container, owner)
    assert loop.target_id == session.id
    epoch = await managers.steps.begin_run(ctx, session.id)
    await managers.agent_sessions.project_status(ctx, session.id)
    written = session.updated_at + timedelta(minutes=21)
    await managers.steps.append_steps(ctx, session.id, epoch, [a_model_request(message, written)])
    row = await managers.agent_sessions.get_session(owner, session.id)
    assert (row.status, row.version) == (SessionStatus.PENDING, session.version)

    work = container.storage.get_work_storage()
    key = derived_id(row.id, row.updated_at, f"stalled:{row.version}")
    later = written + timedelta(minutes=1)
    await a_sweep(container, later)(request())
    assert await work.read_item_by_key(owner.org_id, key) is None, "its loop is claimed"
    await managers.work.fail_for_good(ctx, loop, "the runner refused it")
    await a_sweep(container, later)(request())
    assert await work.read_item_by_key(owner.org_id, key) is None, "its last step is recent"

    quiet = written + StalledOptions().stall_after + timedelta(minutes=1)
    await a_sweep(container, quiet)(request())
    asked = await work.read_item_by_key(owner.org_id, key)
    assert asked is not None
    assert (asked.kind, asked.target_id) == (WorkKind.LOOP, session.id)
