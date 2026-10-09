"""Placement over memory: each kind of a session's work goes to the lane
where its environment is and is claimed only from it, a host is claimed
for by the control plane by its identity alone, a tenant's fair share is
held at the claim as the work queue's cap, its tier's or its own, a share
the release before wrote is carried into that cap once, and a runner that
lost its claim is refused while a new claim from the same lane recovers the
session."""

import asyncio
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from contracts.doubles import Members
from contracts.loops import loop_over, reply, said, use
from contracts.placement_storage import make_share
from contracts.tools import stand_ins

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id, utcnow
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    OperatorContext,
    OperatorRole,
    RequestContext,
    TenantContext,
)
from acme.om.exceptions import LeaseLost, NotAuthorized, NotFound, ValidationFailed
from acme.om.placement.impl.manager import PlacementManagerImpl, PlacementOptions
from acme.om.placement.impl.operator import SHARE_SET_KIND
from acme.om.placement.kinds import (
    HOST,
    PLACED_KINDS,
    claims_of,
    platform_claimant_kinds,
    platform_work_kinds,
)
from acme.om.placement.rules import host_lane, own_lane, pool_lane, tier_lane
from acme.om.placement.storage.impl.memory import PlacementStorageMemoryImpl
from acme.om.placement.types.claimant import Claimant
from acme.om.placement.types.share import TierShare
from acme.om.placement.types.work import ExecOperation, ExecPayload, WorkspaceOperation
from acme.om.root import Managers, build_managers
from acme.om.steps.rules import message_step
from acme.om.steps.types.header import LoopOutcome
from acme.om.steps.types.step import StepType
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tenancy.rules import operator_permissions_of
from acme.om.work.impl.manager import DEAD_LETTER_KIND
from acme.om.work.storage.impl.memory import WorkStorageMemoryImpl
from acme.om.work.types.work_item import WorkItem, WorkKind, WorkStatus

LEASE = timedelta(seconds=30)
APP = AppContext(type=AppType.PORTAL, version="portal@test")
WORKER = AppContext(type=AppType.WORKER, version="worker@test")
# What `make_session` names, so the agents manager classes every tool it
# offers.
TOOLS = stand_ins("read_log", "run_tests")


def request(app: AppContext = WORKER) -> RequestContext:
    return RequestContext(request_id=new_id(), app=app)


def operator(role: OperatorRole = OperatorRole.WRITE) -> OperatorContext:
    """A test double of the operator stage; admission is the tenancy
    manager's, and this suite is about placement."""
    return OperatorContext(
        request_id=new_id(),
        app=AppContext(type=AppType.CLI, version="ops@test"),
        identity_id=new_id(),
        email="root@example.test",
        credential_kind=CredentialKind.LOGIN,
        credential_id=new_id(),
        permissions=operator_permissions_of(role),
    )


@pytest.fixture
def storage() -> StorageMemoryImpl:
    return StorageMemoryImpl()


@pytest.fixture
def managers(tmp_path: Path, storage: StorageMemoryImpl) -> Managers:
    return build_managers(storage, InfraLocalImpl(tmp_path), tool_catalog=TOOLS)


async def an_owner(managers: Managers, slug: str = "ajax") -> TenantContext:
    owner, _ = await managers.tenancy.bootstrap(
        request(APP), slug.title(), slug, f"ann@{slug}.test", "Ann"
    )
    return owner


def an_item(ctx: TenantContext, kind: WorkKind, payload: Mapping[str, object]) -> WorkItem:
    now = utcnow()
    return WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        kind=kind,
        target_id=new_id(),
        idempotency_key=new_id(),
        request_id=new_id(),
        payload=payload,
        # What a producer names is never where the item goes.
        lane="default",
        available_at=now,
    )


def exec_on(host: UUID) -> dict[str, object]:
    """An `exec` item's payload as the relay writes one, for `host`."""
    spec = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))
    payload = ExecPayload(
        host_id=host,
        item_id=new_id(),
        session_id=new_id(),
        key=new_id(),
        operation=ExecOperation.RUN,
        effect="unsafe",
        spec=spec,
        isolation="container",
        egress=(),
        reads=("/srv/work",),
    )
    return payload.model_dump(mode="json")


def prepare_in(pool: UUID) -> dict[str, object]:
    return {"operation": WorkspaceOperation.PREPARE.value, "pool_id": str(pool)}


def release_on(host: UUID) -> dict[str, object]:
    return {"operation": WorkspaceOperation.RELEASE.value, "host_id": str(host)}


def items_of(storage: StorageMemoryImpl) -> list[WorkItem]:
    work = storage.get_work_storage()
    assert isinstance(work, WorkStorageMemoryImpl)
    return [item for _, item in work._items.values()]  # pyright: ignore[reportPrivateUsage]


# Each kind goes to the lane where its environment is.


async def test_each_kind_goes_to_the_lane_where_its_environment_is(managers: Managers) -> None:
    owner = await an_owner(managers)
    host, pool = new_id(), new_id()
    cases = {
        (WorkKind.LOOP, ()): tier_lane("standard"),
        (WorkKind.EXEC, ("host",)): host_lane(host),
        (WorkKind.WORKSPACE, ("prepare",)): pool_lane(pool),
        (WorkKind.WORKSPACE, ("release",)): host_lane(host),
        (WorkKind.VALIDATION, ()): "default",
        (WorkKind.NOOP, ()): "default",
    }
    payloads: dict[tuple[str, ...], dict[str, object]] = {
        (): {},
        ("host",): exec_on(host),
        ("prepare",): prepare_in(pool),
        ("release",): release_on(host),
    }
    for (kind, which), lane in cases.items():
        queued = await managers.work.enqueue(owner, an_item(owner, kind, payloads[which]))
        assert queued.lane == lane, kind.value


async def test_a_tenants_loops_go_to_its_tiers_lane_or_its_own(managers: Managers) -> None:
    owner = await an_owner(managers)
    admin = operator()

    async def loop_lane() -> str:
        queued = await managers.work.enqueue(owner, an_item(owner, WorkKind.LOOP, {}))
        return queued.lane

    assert await loop_lane() == tier_lane("standard"), "no share is the default tier"
    await managers.placement_operator.set_share(
        admin, owner.org_id, plan_tier="pro", own_lane=False, concurrency=4
    )
    assert await loop_lane() == tier_lane("pro")
    await managers.placement_operator.set_share(
        admin, owner.org_id, plan_tier="pro", own_lane=True, concurrency=4
    )
    assert await loop_lane() == own_lane(owner.org_id)


async def test_a_relayed_loop_lands_in_its_tenants_lane(
    managers: Managers, storage: StorageMemoryImpl
) -> None:
    """What wakes a session asks for its loop through the outbox, and the
    relayed item is placed like a direct one."""
    owner = await an_owner(managers)
    await managers.placement_operator.set_share(
        operator(), owner.org_id, plan_tier="pro", own_lane=False, concurrency=4
    )
    session = await managers.agent_sessions.create_session(owner, make_session())
    said_now = message_step(new_id(), utcnow(), session.id, owner, "Why does checkout time out?")
    await managers.agent_sessions.receive(owner, session.id, [said_now])
    (loop,) = [i for i in items_of(storage) if i.kind == WorkKind.LOOP]
    assert loop.lane == tier_lane("pro") and loop.target_id == session.id


# Each kind is claimed only from its own lane, and a host by the control
# plane, for its identity.


async def test_each_kind_is_claimed_only_from_its_own_lane(
    managers: Managers, storage: StorageMemoryImpl
) -> None:
    owner = await an_owner(managers)
    mine, theirs = new_id(), new_id()
    my_pool, their_pool = new_id(), new_id()
    host = Claimant(kind=HOST, id=mine, org_id=owner.org_id, pool_id=my_pool)
    enqueued: dict[str, WorkItem] = {}
    for name, kind, payload in (
        ("loop", WorkKind.LOOP, {}),
        ("my exec", WorkKind.EXEC, exec_on(mine)),
        ("their exec", WorkKind.EXEC, exec_on(theirs)),
        ("my prepare", WorkKind.WORKSPACE, prepare_in(my_pool)),
        ("their prepare", WorkKind.WORKSPACE, prepare_in(their_pool)),
        ("my release", WorkKind.WORKSPACE, release_on(mine)),
    ):
        enqueued[name] = await managers.work.enqueue(owner, an_item(owner, kind, payload))

    # A runner claims from a loop lane, and only a loop is there.
    runner = await managers.work.claim(
        request(), tier_lane("standard"), list(WorkKind), "runner-1", LEASE
    )
    assert runner is not None and runner[1].id == enqueued["loop"].id
    assert (
        await managers.work.claim(
            request(), tier_lane("standard"), list(WorkKind), "runner-1", LEASE
        )
        is None
    )

    # The host: its own lane first, then its pool's; nothing of another
    # host's or another pool's.
    handed: list[WorkItem] = []
    while (claimed := await managers.placement.claim_for(request(), host, LEASE)) is not None:
        handed.append(claimed[1])
    assert [i.id for i in handed] == [
        enqueued[name].id for name in ("my exec", "my release", "my prepare")
    ]
    assert {i.claimed_by for i in handed} == {f"host:{mine}"}

    # What is left waits for the host and the pool it was placed for.
    left = {(i.id, i.lane) for i in items_of(storage) if i.status is WorkStatus.QUEUED}
    assert left == {
        (enqueued["their exec"].id, host_lane(theirs)),
        (enqueued["their prepare"].id, pool_lane(their_pool)),
    }


def test_a_claimants_lanes_and_kinds_are_read_off_its_identity_alone() -> None:
    host_id, pool, org = new_id(), new_id(), new_id()
    host = Claimant(kind=HOST, id=host_id, org_id=org, pool_id=pool)
    claimants, work = platform_claimant_kinds(), platform_work_kinds()
    assert claims_of(claimants, work, host) == (
        (host_lane(host_id), (WorkKind.EXEC, WorkKind.WORKSPACE)),
        (pool_lane(pool), (WorkKind.WORKSPACE,)),
    )
    claimed = {kind for _, kinds in claims_of(claimants, work, host) for kind in kinds}
    assert claimed == {spec.name for spec in PLACED_KINDS} == work.claimed_by(HOST)
    with pytest.raises(ValueError, match="pool_id"):
        Claimant.model_validate({"kind": HOST, "id": new_id()})


async def test_work_routed_into_another_tenants_wall_is_never_handed_over(
    managers: Managers,
) -> None:
    """A host inside one tenant's wall is never handed another tenant's work,
    even routed to its lane: the item fails for good, a dead letter, and is
    never claimed again. A host of the platform's own pool serves every
    tenant."""
    ajax, beta = await an_owner(managers, "ajax"), await an_owner(managers, "beta")
    walled_id, cloud_id, pool = new_id(), new_id(), new_id()
    walled = Claimant(kind=HOST, id=walled_id, org_id=ajax.org_id, pool_id=pool)
    cloud = Claimant(kind=HOST, id=cloud_id, pool_id=new_id())
    stray = await managers.work.enqueue(beta, an_item(beta, WorkKind.EXEC, exec_on(walled_id)))
    served = await managers.work.enqueue(beta, an_item(beta, WorkKind.EXEC, exec_on(cloud_id)))

    assert await managers.placement.claim_for(request(), walled, LEASE) is None
    failed = await managers.work.claim(request(), stray.lane, list(WorkKind), "x", LEASE)
    assert failed is None, "never claimed again"
    events = await managers.events.get_events(beta, after_seq=0, limit=10)
    (dead,) = [e for e in events if e.kind == DEAD_LETTER_KIND]
    assert dead.target_id == stray.id and "another tenant" in str(dead.payload["last_error"])

    claimed = await managers.placement.claim_for(request(), cloud, LEASE)
    assert claimed is not None and claimed[1].id == served.id
    assert claimed[0].org_id == beta.org_id


# A tenant's share is held at the claim, as the work queue's cap.


def test_each_loop_lane_passes_its_tiers_share_or_the_default() -> None:
    options = PlacementOptions(tier_shares=(TierShare(tier="pro", share=3),), default_share=5)
    assert options.lane_cap(tier_lane("pro")) == 3
    assert options.lane_cap(tier_lane("standard")) == 5, "a tier with no share of its own"
    assert options.lane_cap(own_lane(new_id())) == 5, "a tenant's own lane"


async def test_a_tenant_at_its_tiers_share_is_passed_over_and_its_own_cap_holds_instead(
    tmp_path: Path, storage: StorageMemoryImpl
) -> None:
    options = PlacementOptions(tier_shares=(TierShare(tier="standard", share=1),))
    managers = build_managers(
        storage, InfraLocalImpl(tmp_path), tool_catalog=TOOLS, placement_options=options
    )
    ajax, beta = await an_owner(managers, "ajax"), await an_owner(managers, "beta")
    lane = tier_lane("standard")
    cap = options.lane_cap(lane)
    for owner in (ajax, ajax, ajax, beta):
        await managers.work.enqueue(owner, an_item(owner, WorkKind.LOOP, {}))

    async def claim() -> tuple[TenantContext, WorkItem] | None:
        return await managers.work.claim(
            request(), lane, [WorkKind.LOOP], "runner", LEASE, tenant_cap=cap
        )

    first, second = await claim(), await claim()
    assert first is not None and first[0].org_id == ajax.org_id
    assert second is not None and second[0].org_id == beta.org_id, "Ajax is at its share"
    assert await claim() is None, "Ajax's next loops wait"
    waiting = [i for i in items_of(storage) if i.status is WorkStatus.QUEUED]
    assert [(i.attempts, i.claimed_by) for i in waiting] == [(0, None)] * 2

    # Its own cap, set on its share, holds in place of its tier's.
    await managers.placement_operator.set_share(
        operator(), ajax.org_id, plan_tier="standard", own_lane=False, concurrency=2
    )
    third = await claim()
    assert third is not None and third[0].org_id == ajax.org_id
    assert await claim() is None, "two of Ajax's loops run, its own cap"


async def test_a_tenant_moved_to_another_lane_keeps_its_own_cap_on_the_lane_it_left(
    managers: Managers,
) -> None:
    owner = await an_owner(managers)
    admin = operator()
    work = managers.work_operator
    tier, own = tier_lane("pro"), own_lane(owner.org_id)

    async def caps() -> dict[str, int]:
        found: dict[str, int] = {}
        for lane in (tier, own):
            try:
                found[lane] = (await work.read_tenant_cap(admin, owner.org_id, lane)).cap
            except NotFound:
                pass
        return found

    set_at = await managers.placement_operator.set_share(
        admin, owner.org_id, plan_tier="pro", own_lane=False, concurrency=1
    )
    assert (set_at.concurrency, set_at.own_cap) == (1, True)
    for _ in range(3):
        await managers.work.enqueue(owner, an_item(owner, WorkKind.LOOP, {}))
    await managers.placement_operator.set_share(
        admin, owner.org_id, plan_tier="pro", own_lane=True, concurrency=2
    )
    assert await caps() == {tier: 1, own: 2}, "the cap on the lane it left stays"

    # Its backlog stays on the tier's lane, held to its own cap there, not
    # to the tier's share.
    async def claim() -> tuple[TenantContext, WorkItem] | None:
        return await managers.work.claim(
            request(), tier, [WorkKind.LOOP], "runner", LEASE, PlacementOptions().lane_cap(tier)
        )

    assert await claim() is not None
    assert await claim() is None, "one of its loops runs on the lane it left, its cap there"

    cleared = await managers.placement_operator.set_share(
        admin, owner.org_id, plan_tier="pro", own_lane=True
    )
    assert await caps() == {tier: 1}, "none clears the cap on the lane it names alone"
    assert (cleared.concurrency, cleared.own_cap) == (PlacementOptions().default_share, False)
    await managers.placement_operator.set_share(
        admin, owner.org_id, plan_tier="pro", own_lane=False, concurrency=3
    )
    assert await caps() == {tier: 3}, "a move back writes the cap it left"


async def test_after_a_move_the_standing_reads_the_cap_and_the_claims_of_its_loops_lane(
    managers: Managers,
) -> None:
    owner = await an_owner(managers)
    admin = operator()
    tier, own = tier_lane("pro"), own_lane(owner.org_id)
    await managers.placement_operator.set_share(
        admin, owner.org_id, plan_tier="pro", own_lane=False, concurrency=1
    )
    await managers.work.enqueue(owner, an_item(owner, WorkKind.LOOP, {}))
    running = await managers.work.claim(
        request(), tier, [WorkKind.LOOP], "runner", LEASE, PlacementOptions().lane_cap(tier)
    )
    assert running is not None
    before = await managers.agent_sessions.create_session(owner, make_session())
    await managers.work.enqueue(
        owner, an_item(owner, WorkKind.LOOP, {}).model_copy(update={"target_id": before.id})
    )
    await managers.placement_operator.set_share(
        admin, owner.org_id, plan_tier="pro", own_lane=True, concurrency=2
    )
    after = await managers.agent_sessions.create_session(owner, make_session())
    await managers.work.enqueue(
        owner, an_item(owner, WorkKind.LOOP, {}).model_copy(update={"target_id": after.id})
    )

    async def standing(session: UUID) -> tuple[object, ...]:
        found = await managers.placement_operator.get_session_standing(admin, owner.org_id, session)
        assert found.loop is not None
        return (found.loop.lane, found.concurrency, found.own_cap, found.loop.running_ahead)

    assert await standing(before.id) == (tier, 1, True, 1), "queued where it was, at its cap"
    assert await standing(after.id) == (own, 2, True, 0), "none of its claims on its own lane"


# A share the release before wrote is carried into the tenant's own cap.


async def test_the_carry_writes_each_shares_concurrency_as_its_own_cap_once(
    managers: Managers, storage: StorageMemoryImpl
) -> None:
    shares = storage.get_placement_storage()
    assert isinstance(shares, PlacementStorageMemoryImpl)
    ajax, beta = await an_owner(managers, "ajax"), await an_owner(managers, "beta")
    gamma = await an_owner(managers, "gamma")
    shares.written_before(ajax.org_id, make_share(plan_tier="pro"), 2)
    shares.written_before(beta.org_id, make_share(plan_tier="pro", own_lane=True), 3)
    # Gamma's operator set a cap of its own already, which the carry keeps.
    shares.written_before(gamma.org_id, make_share(plan_tier="pro"), 5)
    await managers.work_operator.set_tenant_cap(operator(), gamma.org_id, tier_lane("pro"), 4)

    assert await managers.placement_operator.carry_caps(10) == 3
    assert await managers.placement_operator.carry_caps(10) == 0, "each one once"

    async def cap(org: TenantContext, lane: str) -> int:
        return (await managers.work_operator.read_tenant_cap(operator(), org.org_id, lane)).cap

    assert await cap(ajax, tier_lane("pro")) == 2
    assert await cap(beta, own_lane(beta.org_id)) == 3
    assert await cap(gamma, tier_lane("pro")) == 4
    # Cleared after the carry, a cap stays cleared.
    await managers.work_operator.clear_tenant_cap(operator(), ajax.org_id, tier_lane("pro"))
    assert await managers.placement_operator.carry_caps(10) == 0
    with pytest.raises(NotFound):
        await cap(ajax, tier_lane("pro"))


# The operators' plane writes a share; a tenant never does.


async def test_an_operator_sets_a_share_in_versions_and_the_stream_names_them(
    managers: Managers,
) -> None:
    owner = await an_owner(managers)
    admin = operator()
    first = (
        await managers.placement_operator.set_share(
            admin, owner.org_id, plan_tier="pro", own_lane=False, concurrency=3
        )
    ).share
    second = (
        await managers.placement_operator.set_share(
            admin, owner.org_id, plan_tier="pro", own_lane=True, concurrency=5
        )
    ).share
    assert (first.version, second.version, second.id) == (1, 2, first.id)
    assert second.created_by == second.updated_by == admin.identity_id
    events = await managers.events.get_events(owner, after_seq=0, limit=10)
    assert [(e.kind, e.actor_id, e.payload["version"]) for e in events] == [
        (SHARE_SET_KIND, admin.identity_id, 1),
        (SHARE_SET_KIND, admin.identity_id, 2),
    ]
    assert events[-1].payload == {
        "plan_tier": "pro",
        "own_lane": True,
        "concurrency": 5,
        "version": 2,
    }


async def test_a_share_is_refused_to_a_reader_an_unknown_org_and_bad_terms(
    managers: Managers,
) -> None:
    owner = await an_owner(managers)
    terms = {"plan_tier": "pro", "own_lane": False, "concurrency": 2}
    with pytest.raises(NotAuthorized):
        await managers.placement_operator.set_share(
            operator(OperatorRole.READ), owner.org_id, **terms
        )
    with pytest.raises(NotFound):
        await managers.placement_operator.set_share(operator(), new_id(), **terms)
    for bad in ({"plan_tier": "Pro:x"}, {"concurrency": 0}, {"concurrency": 10_001}):
        with pytest.raises(ValidationFailed):
            await managers.placement_operator.set_share(
                operator(), owner.org_id, **{**terms, **bad}
            )
    assert await managers.events.get_events(owner, after_seq=0, limit=10) == []
    with pytest.raises(NotFound):
        await managers.work_operator.read_tenant_cap(operator(), owner.org_id, tier_lane("pro"))


async def test_a_tenant_past_its_retention_loses_its_share_and_a_living_one_keeps_it(
    managers: Managers, storage: StorageMemoryImpl
) -> None:
    owner = await an_owner(managers)
    await managers.placement_operator.set_share(
        operator(), owner.org_id, plan_tier="pro", own_lane=False, concurrency=2
    )
    members = Members()  # pyright: ignore[reportAbstractUsage] (a partial double)
    shares = storage.get_placement_storage()
    placement = PlacementManagerImpl(
        shares,
        managers.work,
        members,
        PlacementOptions(),
        platform_work_kinds(),
        platform_claimant_kinds(),
    )
    assert await placement.purge_tenant(owner) == 0, "a living tenant keeps it"
    assert await shares.read_share(owner.org_id) is not None
    members.expired = True
    assert await placement.purge_tenant(owner) == 1
    assert await shares.read_share(owner.org_id) is None


# A runner that lost its claim writes nothing, and a new claim recovers.


async def test_a_lost_claim_writes_nothing_and_the_next_claim_recovers_the_session(
    tmp_path: Path,
) -> None:
    """The loop's item is claimed from its tenant's lane; the runner stalls
    past its lease, so the sweep puts the item back, and a second runner
    claims it from the same lane. A cap of one does not hold the recovery
    back, since the lost claim no longer counts. The new
    run takes the next epoch, so the stalled run appends nothing and
    settles nothing in the queue."""
    storage = StorageMemoryImpl()
    managers = build_managers(storage, InfraLocalImpl(tmp_path / "boot"))
    owner = await an_owner(managers)
    await managers.placement_operator.set_share(
        operator(), owner.org_id, plan_tier="standard", own_lane=False, concurrency=1
    )
    loop = loop_over(tmp_path, storage=storage, owner=owner)
    session_id = await loop.start()
    message = message_step(new_id(), utcnow(), session_id, owner, "Note the fix.")
    await loop.managers.agent_sessions.receive(owner, session_id, [message])
    loop.anthropic.add(
        reply(use("slow", use_id="use_slow"), use("note", use_id="use_note")),
        reply(said("The note did not finish; I checked.")),
    )
    lane = tier_lane("standard")
    work = loop.managers.work

    lost = await work.claim(
        request(), lane, [WorkKind.LOOP], "runner-a", timedelta(milliseconds=50)
    )
    assert lost is not None
    stalled = asyncio.ensure_future(loop.loops.run(lost[0], session_id))
    await loop.tools["slow"].started.wait()
    await asyncio.sleep(0.1)
    assert await work.requeue_stale(request(), 100) == 1, "its lease ran out"

    found = await work.claim(request(), lane, [WorkKind.LOOP], "runner-b", LEASE)
    assert found is not None and found[1].id == lost[1].id, "the lost claim does not count"
    run = await loop.loops.run(found[0], session_id)
    loop.tools["slow"].release.set()
    stale = await stalled

    assert run.outcome is LoopOutcome.SUCCEEDED and stale.end is RunEnd.STALE
    assert stale.epoch < run.epoch
    assert loop.tools["note"].ran_as == [], "an unsafe call is never repeated"
    answers = [s for s in await loop.history(session_id) if s.type is StepType.TOOL_RESPONSE]
    assert len(answers) == 2, "the new run's answers, and nothing of the stalled run's"
    with pytest.raises(LeaseLost):
        await work.complete(lost[0], lost[1])
    done = await work.complete(found[0], found[1])
    assert done.status is WorkStatus.DONE
