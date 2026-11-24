"""The cloud pool's hibernated warm VMs, over the VMs' twin where it
hibernates them. A warm VM started to sleep boots the pool's image under a
one-use key, and once it settled one sweep ends its key and hibernates it,
so it sleeps holding no key that enrolls; a claim writes the digest of a
fresh key before it wakes it, and its host enrolls with that key for the
claiming session alone. A VM that served a session never sleeps, and one
asleep counts toward the pool's maximum and toward the hibernated count,
which holds apart from the running one. A claim takes a warm VM that runs,
then one asleep, then a new one, each counted under its own source. The
sweep lets one asleep go past the pool's maximum age, or near the longest
its VMs keep one hibernated, and one that cannot hibernate goes rather
than stay awake. Where the VMs hibernate none, the tier is off."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from unit.test_cloud_pool import (
    ENROLLMENT,
    MEDIUM,
    OPEN,
    Pool,
    claims,
    counted_since,
    stage,
)

from acme.infra.exceptions import InfraValidationFailed
from acme.infra.vms import VmSpec, VmState
from acme.om.base import new_id, utcnow
from acme.om.cloud_pool.exceptions import VmUnbound
from acme.om.cloud_pool.rules import slept_out
from acme.om.cloud_pool.types.limits import PoolLimits
from acme.om.cloud_pool.types.vm import PoolVm
from acme.om.context import Role, TenantContext
from acme.om.exceptions import InvalidCredential
from acme.om.tenancy.rules import hash_token

from contracts.doubles import context
from contracts.factories import make_org

SLEEPS = timedelta(days=60)
"""As long as the cloud's VMs keep one hibernated."""


@pytest.fixture
def ctx() -> TenantContext:
    return context(Role.SERVICE, make_org())


async def swept(pool: Pool) -> None:
    await pool.manager.sweep(stage())
    await pool.manager.close()


async def asleep(pool: Pool) -> list[PoolVm]:
    """The pool's warm VMs started to sleep, asleep: one sweep starts them,
    and the next, once they settled, hibernates them."""
    await swept(pool)
    pool.now += pool.options.settle
    await swept(pool)
    return [row for row in await pool.rows() if row.asleep]


def hibernated(pool: Pool, name: str) -> int:
    """How many times the pool hibernated the VM under `name`."""
    return pool.vms.calls.count(("hibernate", name))


async def write_limits(pool: Pool, *, warm: int, hibernated: int, most: int) -> None:
    now = utcnow()
    stored = await pool.storage.read_limits()
    await pool.storage.write_limits(
        PoolLimits(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=new_id(),
            updated_by=new_id(),
            warm=warm,
            hibernated=hibernated,
            most=most,
            tenant_most=most,
            version=1 if stored is None else stored.version + 1,
        ),
        None if stored is None else stored.version,
    )


async def test_a_vm_sleeps_holding_no_key_that_enrolls_and_wakes_under_a_fresh_one_for_its_claim(
    tmp_path: Path, ctx: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = Pool(tmp_path, hibernated=1, hibernation=SLEEPS)
    await pool.image()
    await swept(pool)
    (settling,) = await pool.rows()
    assert settling.hibernates and settling.started_at is not None and not settling.asleep
    old_key = pool.seed(settling.name)["key"]
    with pytest.raises(VmUnbound):
        await pool.manager.enroll(stage(), old_key, ENROLLMENT)
    pool.now += pool.options.settle - timedelta(seconds=1)
    await swept(pool)
    assert hibernated(pool, settling.name) == 0, "it settles first"

    pool.now += timedelta(seconds=1)
    await swept(pool)
    (slept,) = await pool.rows()
    assert slept.asleep and slept.key_digest is None, "its key ended before it slept"
    assert hibernated(pool, slept.name) == 1
    assert await pool.vms.state(slept.name) is VmState.STOPPED
    assert pool.seed(slept.name)["key"] == old_key, "what its memory held as it slept"
    with pytest.raises(InvalidCredential):
        await pool.manager.enroll(stage(), old_key, ENROLLMENT)

    woken: list[tuple[VmState, PoolVm | None]] = []
    launch = pool.vms.launch

    async def waking(name: str, spec: VmSpec, snapshot: str | None = None) -> None:
        if name == slept.name:  # the refill starts another to sleep beside it
            woken.append((await pool.vms.state(name), await pool.storage.read_by_name(name)))
        await launch(name, spec, snapshot)

    monkeypatch.setattr(pool.vms, "launch", waking)
    agent_session_id = new_id()
    await pool.prepare(ctx, agent_session_id)
    await pool.manager.close()
    monkeypatch.undo()

    ((state, at_wake),) = woken
    assert state is VmState.STOPPED and at_wake is not None, "woken from its sleep"
    assert at_wake.agent_session_id == agent_session_id, "bound to its claim before it woke"
    fresh_key = pool.seed(slept.name)["key"]
    assert fresh_key != old_key
    assert at_wake.key_digest == hash_token(fresh_key), "the fresh key's digest, before it woke"
    (row,) = [row for row in await pool.rows() if row.agent_session_id == agent_session_id]
    assert row.id == slept.id and row.host_id is not None and row.key_digest is None
    (admitted,) = pool.hosts.admitted
    assert admitted[2] == row.id
    (pooled,) = pool.placed.pools
    assert pooled is not None and pooled.pool is not None
    assert admitted[1] == pooled.pool.id, "the claiming session's pool of one"
    assert pooled.pool.agent_session_id == agent_session_id
    for key in (old_key, fresh_key):
        with pytest.raises(InvalidCredential):
            await pool.manager.enroll(stage(), key, ENROLLMENT)


async def test_a_vm_that_served_a_session_never_sleeps_and_one_asleep_counts_toward_both_limits(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, warm=1, hibernated=2, most=10, tenant_most=10, hibernation=SLEEPS)
    await pool.image()
    sleepers = await asleep(pool)
    assert len(sleepers) == 2, "the hibernated count, apart from the warm one that runs"
    await swept(pool)
    rows = await pool.rows()
    assert sum(row.warm and row.hibernates for row in rows) == 2, "no more than its own count"
    assert sum(row.warm and not row.hibernates for row in rows) == 1

    # Each kind of claim, no refill standing another in its place: a warm
    # VM taken running, one woken, a new one. Their hosts call on.
    await write_limits(pool, warm=0, hibernated=0, most=10)
    served = []
    for spec in (OPEN, OPEN, MEDIUM):
        agent_session_id = new_id()
        await pool.prepare(ctx, agent_session_id, spec)
        (row,) = [row for row in await pool.rows() if row.agent_session_id == agent_session_id]
        served.append(row)
    await pool.manager.close()
    assert [row.hibernates for row in served] == [False, True, False]
    for _ in range(3):
        pool.now += pool.options.settle + pool.options.boot + pool.options.ready_wait
        for row in served:
            assert row.host_id is not None
            pool.hosts.seen[row.host_id].last_seen_at = pool.now
        await swept(pool)
    asleep_once = {row.id for row in served if row.hibernates}
    for row in served:
        assert hibernated(pool, row.name) == (1 if row.id in asleep_once else 0), (
            "a VM that served a session never sleeps again, nor ever did when it ran"
        )

    # Its host silent, a session's VM stops, its disk kept: never hibernates.
    pool.now += pool.options.silent + timedelta(minutes=1)
    await swept(pool)
    for row in served:
        assert await pool.vms.state(row.name) is VmState.STOPPED
        assert hibernated(pool, row.name) == (1 if row.id in asleep_once else 0)
        assert ("stop", row.name) in pool.vms.calls

    # At the maximum, a VM asleep holds its place: a refill starts none past
    # it, and a claim that takes no warm VM takes the place of an idle one.
    capped = Pool(tmp_path / "capped", hibernated=2, most=3, tenant_most=10, hibernation=SLEEPS)
    await capped.image()
    assert len(await asleep(capped)) == 2
    await capped.prepare(ctx, new_id(), MEDIUM)
    assert len(await capped.rows()) == 3, "the two asleep count: the pool stands at its most"
    await capped.prepare(ctx, new_id(), MEDIUM)
    await swept(capped)
    rows = await capped.rows()
    assert len(rows) == 3 and sum(row.asleep for row in rows) == 1, (
        "one asleep made way, and none starts past the most"
    )


async def test_a_claim_takes_a_warm_vm_that_runs_then_one_asleep_then_a_new_one(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, warm=1, hibernated=1, hibernation=SLEEPS)
    await pool.image()
    assert len(await asleep(pool)) == 1
    (running,) = [row for row in await pool.rows() if row.warm and not row.hibernates]
    (sleeping,) = [row for row in await pool.rows() if row.asleep]
    assert running.created_at <= sleeping.created_at
    # No refill stands another in their place, so each claim shows its own.
    await write_limits(pool, warm=0, hibernated=0, most=20)

    got: list[tuple[str, dict[str, float]]] = []
    for _ in range(3):
        before = claims()
        agent_session_id = new_id()
        await pool.prepare(ctx, agent_session_id)
        await pool.manager.close()
        (row,) = [row for row in await pool.rows() if row.agent_session_id == agent_session_id]
        got.append((row.name, counted_since(before)))
    assert got[0] == (running.name, {"warm": 1}), "the one that runs first"
    assert got[1] == (sleeping.name, {"hibernated": 1}), "then the one asleep"
    assert got[2][0] not in (running.name, sleeping.name) and got[2][1] == {"new": 1}


async def test_the_sweep_lets_a_vm_asleep_go_past_the_pools_age_or_near_its_vms_bound(
    tmp_path: Path,
) -> None:
    assert not slept_out(timedelta(days=57), SLEEPS)
    assert slept_out(timedelta(days=58), SLEEPS), "two days before the cloud's 60"

    aged = Pool(tmp_path / "aged", hibernated=1, hibernation=SLEEPS)
    await aged.image()
    (old,) = await asleep(aged)
    aged.now = old.created_at + aged.options.max_age
    await swept(aged)
    assert [row.id for row in await aged.rows()] == [old.id], "not past it yet"
    aged.now += timedelta(minutes=1)
    await swept(aged)
    assert await aged.vms.state(old.name) is VmState.ABSENT, "past the pool's maximum age"
    (new,) = await aged.rows()
    assert new.id != old.id and new.hibernates, "and another starts to sleep"

    # A cloud that keeps one hibernated three days: one asleep goes a day
    # in, before the pool's own age would let it go.
    short = Pool(tmp_path / "short", hibernated=1, hibernation=timedelta(days=3))
    await short.image()
    (old,) = await asleep(short)
    assert old.hibernated_at is not None
    short.now = old.hibernated_at + timedelta(hours=23)
    await swept(short)
    assert await short.vms.state(old.name) is VmState.STOPPED
    short.now = old.hibernated_at + timedelta(days=1)
    assert short.now - old.created_at < short.options.max_age
    await swept(short)
    assert await short.vms.state(old.name) is VmState.ABSENT, "near its VMs' bound"


async def test_a_vm_that_cannot_hibernate_goes_and_vms_that_hibernate_none_keep_no_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    off = Pool(tmp_path / "off", hibernated=2)
    await off.image()
    await swept(off)
    assert await off.rows() == [], "where the VMs hibernate none, none starts to sleep"

    pool = Pool(tmp_path / "on", hibernated=1, hibernation=SLEEPS)
    await pool.image()
    await swept(pool)
    (settling,) = await pool.rows()

    async def refused(name: str) -> Any:
        raise InfraValidationFailed("not ready to hibernate")

    monkeypatch.setattr(pool.vms, "hibernate", refused)
    pool.now += pool.options.settle
    await pool.manager.sweep(stage())
    await pool.manager.close()
    assert await pool.vms.state(settling.name) is VmState.ABSENT, "never kept awake instead"
    (another,) = await pool.rows()
    assert another.id != settling.id and another.hibernates
