"""The sweep's platform duties: each tenant ticked once a pass, a deleted
tenant's matrix pins, choices, and spend account gone before it is marked
purged, and the platform's gauges set whole a pass."""

from pathlib import Path
from uuid import UUID

from prometheus_client import REGISTRY
from test_sweep import deleted_org, listed, quiet_outbox, recording, service_contexts
from worker_support import build_container, fast_options

from acme.infra.cache import CacheScope
from acme.om.agent_billing.types.spend_ledger import FundedHold
from acme.om.context import TenantContext
from acme.om.placement.types.standing import AgentFleetCounts, Count
from acme.om.root import KINDS
from acme.om.work import WorkManagerInterface
from acme.workers.maintenance.container import WorkerContainer
from acme.workers.maintenance.loop import (
    AgentFleetStep,
    LoopOptions,
    PurgeStep,
    WorkerLoop,
)
from acme.workers.maintenance.main import build_loop

from contracts.matrix_storage import make_choice, make_pin
from contracts.spend_account_storage import make_spend_account
from contracts.spend_ledger_storage import a_funded_hold, funding


def sweeping(
    container: WorkerContainer,
    work: WorkManagerInterface,
    purges: dict[str, PurgeStep],
    options: LoopOptions,
    agent_fleet: AgentFleetStep | None = None,
) -> WorkerLoop:
    """The loop the engine's suite sweeps with, and the platform's agent fleet
    step."""
    return WorkerLoop(
        work=work,
        outbox=quiet_outbox(),
        purges=purges,
        agent_fleet=agent_fleet,
        kinds=KINDS,
        handlers={},
        topics=container.infra.get_topics(),
        liveness=container.infra.get_cache(CacheScope.WORKER_LIVENESS),
        options=options,
    )


async def test_each_tenant_is_ticked_once_a_pass_and_a_failing_tick_stops_nothing(
    tmp_path: Path,
) -> None:
    """A tick, such as the schedules of a tenant's agent automations, runs once for
    every tenant a pass, before its purges; one that raises is logged, and
    the tenant's other ticks and purges still run."""
    container = build_container(tmp_path)
    contexts = service_contexts(2)
    calls: list[tuple[str, UUID]] = []

    async def broken(ctx: TenantContext) -> None:
        calls.append(("broken", ctx.org_id))
        raise RuntimeError("the schedules could not be read")

    loop = WorkerLoop(
        work=listed(contexts),
        outbox=quiet_outbox(),
        purges={"purge": recording(calls, "purge")},
        ticks={"broken": broken, "tick": recording(calls, "tick")},
        kinds=KINDS,
        handlers={},
        topics=container.infra.get_topics(),
        liveness=container.infra.get_cache(CacheScope.WORKER_LIVENESS),
        options=fast_options(),
    )
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    ids = [ctx.org_id for ctx in sorted(contexts, key=lambda ctx: ctx.org_id)]
    assert calls == [(name, org) for org in ids for name in ("broken", "tick", "purge")]


async def test_a_deleted_tenants_matrix_pins_and_choices_go_before_it_is_marked_purged(
    tmp_path: Path,
) -> None:
    """A session's pin to a matrix version and the tenant's choice of fill,
    which names who made it, go with the purge's models step: the tenant is
    marked purged only once neither is left."""
    container = build_container(tmp_path)
    org_id, _ = await deleted_org(container, days_ago=40)
    matrix = container.storage.get_matrix_tenant_storage()
    pin = make_pin()
    await matrix.write_pin(org_id, pin)
    await matrix.write_override(org_id, make_choice())
    loop = build_loop(container)

    for _ in range(3):
        await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert await matrix.read_pin(org_id, pin.agent_session_id) is None
    assert await matrix.read_overrides(org_id, 10) == []
    marked = await container.storage.get_tenancy_storage().read_org(org_id)
    assert marked is not None and marked.purged_at is not None, "nothing of it was left"


async def test_a_deleted_tenants_account_goes_and_it_is_marked_purged_with_its_money_ledger_kept(
    tmp_path: Path,
) -> None:
    """Every hold, settlement, and charge behind the money gate is an entry
    of agent billing's ledger. The tenant's account goes with its other rows; its
    entries stay, since no serving login deletes one, and they never keep
    the tenant from being marked purged, so the sweep runs its purges no
    more."""
    container = build_container(tmp_path)
    org_id, _ = await deleted_org(container, days_ago=40)
    accounts = container.storage.get_spend_account_storage()
    ledger = container.storage.get_spend_ledger_storage()
    assert await accounts.create_spend_account(org_id, make_spend_account(org_id), ())
    held = await ledger.open_spend_hold(
        org_id, a_funded_hold(units=1, paid_by=funding(included=10))
    )
    assert isinstance(held, FundedHold)
    loop = build_loop(container)
    tenancy = container.storage.get_tenancy_storage()

    for _ in range(3):
        await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert await accounts.read_spend_account(org_id) is None
    assert await ledger.count_tenant(org_id, 10) > 0, "the hold and its counts stay"
    marked = await tenancy.read_org(org_id)
    assert marked is not None and marked.purged_at is not None, "its ledger holds no mark"


async def test_a_pass_sets_the_platforms_gauges_whole_by_their_labels(tmp_path: Path) -> None:
    """The parks, the ready loops, and the hosts, each cleared and set
    whole from one read: a tier no loop waits on any more leaves the gauge,
    and a read that fails leaves every gauge as it was."""
    container = build_container(tmp_path)
    reads: list[AgentFleetCounts | Exception] = [
        AgentFleetCounts(
            parked=(Count(labels=("provider", "under_1h"), value=4),),
            loops_ready=(Count(labels=("pro",), value=2), Count(labels=("(own)",), value=1)),
            hosts=(Count(labels=("online",), value=3),),
        ),
        AgentFleetCounts(parked=(), loops_ready=(Count(labels=("standard",), value=5),), hosts=()),
        RuntimeError("the database is down"),
    ]

    async def agent_fleet() -> AgentFleetCounts:
        read = reads.pop(0)
        if isinstance(read, Exception):
            raise read
        return read

    loop = sweeping(
        container, listed(service_contexts(0)), {}, fast_options(), agent_fleet=agent_fleet
    )
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    sample = REGISTRY.get_sample_value
    assert sample("acme_sessions_parked", {"reason": "provider", "age": "under_1h"}) == 4
    assert sample("acme_loops_ready", {"plan_tier": "pro"}) == 2
    assert sample("acme_loops_ready", {"plan_tier": "(own)"}) == 1
    assert sample("acme_hosts", {"state": "online"}) == 3
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert sample("acme_loops_ready", {"plan_tier": "pro"}) is None
    assert sample("acme_loops_ready", {"plan_tier": "standard"}) == 5
    assert sample("acme_hosts", {"state": "online"}) is None
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert sample("acme_loops_ready", {"plan_tier": "standard"}) == 5
