"""The cloud pool's limits. A claim past the most VMs the pool holds, or
the most its tenant holds, starts no VM: the loop waits on the resource
and asks again, told no count, while another tenant's claim starts one.
At the pool's maximum, a claim that cannot take a warm VM takes the place
of an idle one, which goes first. An operator's write of a limit holds at the next claim, with no restart,
and leaves an audit event that names the operator and the values, the
pool's own in the platform's stream alone. The refill starts warm VMs up
to the warm count, and never past the most."""

from pathlib import Path
from uuid import UUID

import pytest
from unit.test_cloud_pool import MEDIUM, Pool, stage

from acme.infra.agent_workspaces import IsolationRefused
from acme.infra.vms import VmState
from acme.om.base import EMPTY_UUID, new_id
from acme.om.cloud_pool.impl.manager import FULL_CAUSES
from acme.om.cloud_pool.impl.operator import (
    LIMITS_SET_KIND,
    TENANT_LIMIT_CLEARED_KIND,
    TENANT_LIMIT_SET_KIND,
    CloudPoolOperatorManagerImpl,
)
from acme.om.cloud_pool.types.limits import Full
from acme.om.cloud_pool.types.vm import PoolVm
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    OperatorContext,
    OperatorRole,
    Role,
    TenantContext,
)
from acme.om.exceptions import NotAuthorized, NotFound, ValidationFailed
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tenancy.rules import operator_permissions_of

from contracts.doubles import context
from contracts.factories import make_org


def operator(role: OperatorRole = OperatorRole.WRITE) -> OperatorContext:
    """A test double of the operator stage; admission is the tenancy
    manager's."""
    return OperatorContext(
        request_id=new_id(),
        app=AppContext(type=AppType.CLI, version="ops@test"),
        identity_id=new_id(),
        email="root@example.test",
        credential_kind=CredentialKind.LOGIN,
        credential_id=new_id(),
        permissions=operator_permissions_of(role),
    )


def tenant() -> TenantContext:
    return context(Role.SERVICE, make_org())


def launched(pool: Pool) -> int:
    return sum(1 for call in pool.vms.calls if call[0] == "launch")


def told_no_count(refused: IsolationRefused, full: Full) -> None:
    assert refused.clears, "the loop waits on the resource, and asks again"
    assert refused.cause == FULL_CAUSES[full]
    assert refused.cause is not None and not any(ch.isdigit() for ch in refused.cause)


async def test_a_claim_at_the_pools_maximum_starts_no_vm_and_waits_told_no_count(
    tmp_path: Path,
) -> None:
    pool = Pool(tmp_path, most=2, tenant_most=5)
    await pool.image()
    first, second, third = tenant(), tenant(), tenant()
    held = new_id()
    await pool.prepare(first, held)
    await pool.prepare(second, new_id())
    before = launched(pool)
    waiting = new_id()
    with pytest.raises(IsolationRefused) as refused:
        await pool.prepare(third, waiting)
    told_no_count(refused.value, Full.POOL)
    assert launched(pool) == before and len(await pool.rows()) == 2, "no VM started"

    await pool.manager.release(first, held)
    await pool.prepare(third, waiting)
    assert {row.tenant_id for row in await pool.rows()} == {second.org_id, third.org_id}


async def test_a_tenant_at_its_maximum_waits_while_another_tenants_claim_starts_a_vm(
    tmp_path: Path,
) -> None:
    pool = Pool(tmp_path, most=10, tenant_most=1)
    await pool.image()
    mine, theirs = tenant(), tenant()
    await pool.prepare(mine, new_id())
    before = launched(pool)
    with pytest.raises(IsolationRefused) as refused:
        await pool.prepare(mine, new_id())
    told_no_count(refused.value, Full.TENANT)
    assert launched(pool) == before

    await pool.prepare(theirs, new_id())
    assert launched(pool) == before + 1
    assert sorted(str(row.tenant_id) for row in await pool.rows()) == sorted(
        [str(mine.org_id), str(theirs.org_id)]
    )


async def test_a_claim_that_cannot_take_a_warm_vm_takes_an_idle_ones_place_at_the_maximum(
    tmp_path: Path,
) -> None:
    async def warm_one(pool: Pool) -> PoolVm:
        await pool.manager.sweep(stage())
        await pool.manager.close()
        await pool.warm_asks()
        (warm,) = [row for row in await pool.rows() if row.warm]
        assert warm.started_at is not None and len(await pool.rows()) == 3, "at the maximum"
        return warm

    async def took_its_place(pool: Pool, warm: PoolVm, agent_session_id: UUID) -> None:
        rows = await pool.rows()
        assert warm.id not in {row.id for row in rows}, "the warm VM's row went"
        assert await pool.vms.state(warm.name) is VmState.ABSENT, "the warm VM was let go"
        (mine,) = [row for row in rows if row.agent_session_id == agent_session_id]
        assert await pool.vms.state(mine.name) is VmState.RUNNING, "the claim's VM started"
        assert len(rows) == 3 and not any(row.warm for row in rows), "never past the maximum"

    # The VMs close egress, so a session that asks open egress takes no
    # warm VM.
    closed = Pool(tmp_path / "closed", closes_egress=True, warm=1, most=3, tenant_most=10)
    await closed.image()
    ctx = tenant()
    await closed.prepare(ctx, new_id())
    await closed.prepare(ctx, new_id())
    warm = await warm_one(closed)
    before = launched(closed)
    differs = new_id()
    await closed.prepare(ctx, differs)
    assert launched(closed) == before + 1
    await took_its_place(closed, warm, differs)
    await closed.manager.close()

    # A warm VM is the default size, so a session that asks another takes
    # none.
    opened = Pool(tmp_path / "opened", warm=1, most=3, tenant_most=10)
    await opened.image()
    await opened.prepare(ctx, new_id())
    await opened.prepare(ctx, new_id())
    warm = await warm_one(opened)
    larger = new_id()
    await opened.prepare(ctx, larger, MEDIUM)
    await took_its_place(opened, warm, larger)
    await opened.manager.close()


async def test_an_operators_write_holds_at_the_next_claim_and_its_event_names_the_writer(
    tmp_path: Path,
) -> None:
    pool = Pool(tmp_path)
    await pool.image()
    rows = StorageMemoryImpl()
    orgs, events = rows.get_tenancy_storage(), rows.get_change_event_storage()
    org = make_org()
    await orgs.write_org(org.id, org)
    mine, theirs = context(Role.SERVICE, org), tenant()
    plane = CloudPoolOperatorManagerImpl(
        pool.storage, orgs, events, pool.options, clock=lambda: pool.now
    )
    admin = operator()
    assert (await plane.get_limits(admin)).version == 0, "the options hold until a write"
    await pool.prepare(mine, new_id())

    written = await plane.set_limits(admin, warm=0, most=1, tenant_most=5)
    assert await plane.get_limits(admin) == written
    with pytest.raises(IsolationRefused) as refused:
        await pool.prepare(theirs, new_id())
    told_no_count(refused.value, Full.POOL)
    (event,) = await events.read_after(EMPTY_UUID, 0, 10)
    assert (event.kind, event.actor_id, event.target_id) == (
        LIMITS_SET_KIND,
        admin.identity_id,
        written.id,
    )
    assert event.payload == {"warm": 0, "most": 1, "tenant_most": 5, "version": 1}
    assert await events.read_after(org.id, 0, 10) == [], "no tenant's stream tells the pool's size"

    await plane.set_limits(admin, warm=0, most=10, tenant_most=5)
    own = await plane.set_tenant_limit(admin, org.id, most=1)
    with pytest.raises(IsolationRefused) as refused:
        await pool.prepare(mine, new_id())
    told_no_count(refused.value, Full.TENANT)
    await pool.prepare(theirs, new_id())
    cleared = await plane.clear_tenant_limit(admin, org.id)
    assert cleared == own
    await pool.prepare(mine, new_id())
    assert [
        (e.kind, e.actor_id, e.target_id, dict(e.payload))
        for e in await events.read_after(org.id, 0, 10)
    ] == [
        (TENANT_LIMIT_SET_KIND, admin.identity_id, own.id, {"most": 1, "version": 1}),
        (TENANT_LIMIT_CLEARED_KIND, admin.identity_id, own.id, {"version": 1}),
    ]

    with pytest.raises(NotAuthorized):
        await plane.set_limits(operator(OperatorRole.READ), warm=0, most=1, tenant_most=1)
    with pytest.raises(ValidationFailed):
        await plane.set_limits(admin, warm=2, most=2, tenant_most=1)
    with pytest.raises(ValidationFailed):
        await plane.set_tenant_limit(admin, org.id, most=-1)
    with pytest.raises(NotFound):
        await plane.set_tenant_limit(admin, new_id(), most=1)
    with pytest.raises(NotFound):
        await plane.clear_tenant_limit(admin, org.id)
    assert len(await events.read_after(EMPTY_UUID, 0, 10)) == 2, "a refused write leaves none"


async def test_the_refill_starts_warm_vms_up_to_the_warm_count_and_never_past_the_most(
    tmp_path: Path,
) -> None:
    # The VMs close egress, so a session that asks open egress takes no
    # warm VM: each one holds a place of its own.
    pool = Pool(tmp_path, closes_egress=True, warm=3, most=4, tenant_most=4)
    await pool.image()
    imaged = launched(pool)
    ctx = tenant()
    held = new_id()
    await pool.prepare(ctx, held)
    await pool.prepare(ctx, new_id())

    async def swept() -> tuple[int, int]:
        await pool.manager.sweep(stage())
        await pool.manager.close()
        rows = await pool.rows()
        return sum(1 for row in rows if row.warm), len(rows)

    assert await swept() == (2, 4), "two warm VMs: a third passes the most"
    await pool.manager.release(ctx, held)
    assert await swept() == (3, 4), "the warm count stands once there is room"
    assert await swept() == (3, 4)
    assert launched(pool) - imaged == 2 + 3, "two sessions' VMs and three warm ones"
