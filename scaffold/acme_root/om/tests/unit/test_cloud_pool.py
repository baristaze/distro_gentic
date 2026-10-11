"""The cloud pool over the machines' twin: a machine per session, started
from the pool's image, handed a one-use key its host trades once for a
credential of the session's pool of one. A warm machine serves no session
until one claims it, and the pool starts another in its place. A snapshot
ends the host's credential, stops the machine, and keeps its disk; a
restore holds the disk to its digest and starts a machine on a copy of it.
A spec the machines cannot hold is refused for good. The sweep lets go of
a start that died, a machine whose host never came, one whose session is
gone, and one no row holds; a purge, an erase, and a tenant's purge take
the session's disks, and no other session's."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from contracts.doubles import context
from contracts.factories import make_org

from acme.infra.machines import SEED_FILE, MachineSpec, MachineState
from acme.infra.machines.seeded import PLAIN_WRITE, SeedsChannelImpl
from acme.infra.machines.twin import MachinesTwinImpl
from acme.infra.workspaces import (
    Durability,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    ResourceLimits,
    SnapshotRefused,
    Workspace,
    WorkspaceBase,
    WorkspaceLost,
)
from acme.om.base import new_id, utcnow
from acme.om.cloud_pool.exceptions import MachineUnbound
from acme.om.cloud_pool.impl.manager import CloudPoolManagerImpl, CloudPoolOptions
from acme.om.cloud_pool.rules import snapshots_of
from acme.om.cloud_pool.storage.impl.memory import CloudPoolStorageMemoryImpl
from acme.om.cloud_pool.types.machine import PoolMachine
from acme.om.context import AppContext, AppType, RequestContext, Role, TenantContext
from acme.om.exceptions import InvalidCredential
from acme.om.hosts.types.credential import IssuedCredential
from acme.om.hosts.types.host import Advertisement, Enrollment, HostStatus
from acme.om.hosts.types.host import IsolationMode as HostMode
from acme.om.hosts.types.placement import PlacementState
from acme.om.hosts.types.pool import HostPool
from acme.om.workspaces.types.snapshot import KeptSnapshot

PREFIX = "acme-vm-"
IMAGE = "acme-vm-image"
OPEN = IsolationSpec(mode=IsolationMode.VM, egress=EgressPolicy(mode=EgressMode.OPEN))
KEPT = OPEN.model_copy(update={"durability": Durability.SNAPSHOT})
ENROLLMENT = Enrollment(
    name="machine",
    advertisement=Advertisement(os="Linux", isolation_modes=(HostMode.VM,)),
    exec_version=1,
)


def stage() -> RequestContext:
    return RequestContext(request_id=new_id(), app=AppContext(type=AppType.WORKER, version="t"))


class Hosts:
    """What the pool asks of the hosts: a session's pool of one, a machine's
    host admitted into it, and a host's credential ended."""

    def __init__(self) -> None:
        self.admitted: list[tuple[UUID, UUID, UUID]] = []  # host, pool, machine row
        self.retired: list[UUID] = []

    async def session_pool(self, ctx: TenantContext, session_id: UUID, region: str) -> HostPool:
        now = utcnow()
        return HostPool(
            id=UUID(int=session_id.int ^ 1),
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            name=f"cloud-{session_id}",
            region=region,
            session_id=session_id,
        )

    async def admit_machine(
        self,
        rctx: RequestContext,
        org_id: UUID,
        pool_id: UUID,
        created_by: UUID,
        enrolled_with: UUID,
        enrollment: Enrollment,
    ) -> IssuedCredential:
        host_id = new_id()
        self.admitted.append((host_id, pool_id, enrolled_with))
        return IssuedCredential(
            credential="hst_test",
            credential_id=new_id(),
            kind="host",
            claimant_id=host_id,
            pool_id=pool_id,
            expires_at=utcnow() + timedelta(hours=1),
        )

    async def retire_host(
        self, rctx: RequestContext, org_id: UUID, host_id: UUID, by: UUID
    ) -> None:
        self.retired.append(host_id)

    async def get_hosts(self, ctx: TenantContext, pool_id: UUID) -> tuple[HostStatus, ...]:
        return ()


class Placed:
    """The relay's side of a prepare: the workspace the machine's host holds,
    in the session's pool of one."""

    def __init__(self) -> None:
        self.pools: list[PlacementState | None] = []

    async def held_on_host(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spec: IsolationSpec,
        restore: object = None,
        *,
        pooled: PlacementState | None = None,
    ) -> Workspace:
        self.pools.append(pooled)
        return Workspace(id=session_id, org_id=ctx.org_id, spec=spec, location="/workspace")


class Pool:
    def __init__(self, root: Path, *, warm: int = 0, closes_egress: bool = False) -> None:
        self.machines = MachinesTwinImpl(root / "machines", closes_egress=closes_egress)
        self.storage = CloudPoolStorageMemoryImpl()
        self.hosts = Hosts()
        self.placed = Placed()
        self.gone: set[UUID] = set()
        self.now = utcnow()
        self.manager = CloudPoolManagerImpl(
            self.storage,
            self.machines,
            SeedsChannelImpl(self.machines, timedelta(seconds=10), PLAIN_WRITE),
            lambda: cast(Any, self.hosts),
            lambda: cast(Any, self.placed),
            lambda: cast(Any, None),
            CloudPoolOptions(
                prefix=PREFIX,
                image=IMAGE,
                warm=warm,
                api_url="http://gateway.test",
                ready_wait=timedelta(seconds=5),
                boot=timedelta(minutes=15),
                first_poll=timedelta(milliseconds=5),
                last_poll=timedelta(milliseconds=20),
            ),
            session_gone=self.session_gone,
            expired=self.expired,
            stage=stage,
            clock=lambda: self.now,
        )
        self.expired_tenants: set[UUID] = set()

    async def session_gone(self, org_id: UUID, session_id: UUID) -> bool:
        return session_id in self.gone

    async def expired(self, ctx: TenantContext) -> bool:
        return ctx.org_id in self.expired_tenants

    async def image(self) -> None:
        """The pool's image: a stopped machine that holds the host program."""
        await self.machines.launch(IMAGE, MachineSpec(image="twin", egress_open=True))
        (self.machines.root / IMAGE / "host-program").write_text("the host")
        await self.machines.stop(IMAGE)

    def seed(self, name: str) -> dict[str, Any]:
        loaded = json.loads((self.machines.root / name / SEED_FILE).read_text())
        assert isinstance(loaded, dict)
        return cast(dict[str, Any], loaded)

    async def rows(self) -> list[PoolMachine]:
        return await self.storage.read_machines(100)

    async def host_comes(self, session_id: UUID | None = None) -> UUID:
        """Plays the machine's host: once a machine that serves the session
        runs, it trades the key in its seed."""
        while True:
            for row in await self.rows():
                if (session_id is None or row.session_id == session_id) and (
                    row.started_at is not None and row.key_digest is not None
                ):
                    key = self.seed(row.name)["key"]
                    issued = await self.manager.enroll(stage(), key, ENROLLMENT)
                    return issued.claimant_id
            await asyncio.sleep(0.005)

    async def prepare(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spec: IsolationSpec = OPEN,
        restore: KeptSnapshot | None = None,
    ) -> Workspace:
        host = asyncio.ensure_future(self.host_comes(session_id))
        try:
            return await self.manager.prepare(ctx, session_id, spec, restore)
        finally:
            host.cancel()


@pytest.fixture
async def pool(tmp_path: Path) -> AsyncIterator[Pool]:
    made = Pool(tmp_path)
    await made.image()
    yield made
    await made.manager.close()


@pytest.fixture
def ctx() -> TenantContext:
    return context(Role.SERVICE, make_org())


def kept_record(session_id: UUID, reference: str, digest: str) -> KeptSnapshot:
    now = utcnow()
    return KeptSnapshot(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=new_id(),
        updated_by=new_id(),
        session_id=session_id,
        hash="hmac-sha256:" + "0" * 64,
        size=0,
        reference=reference,
        digest=digest,
        machine=True,
    )


# A machine per session, and its host.


async def test_a_session_gets_a_machine_from_the_pools_image_whose_host_trades_its_key_once(
    pool: Pool, ctx: TenantContext
) -> None:
    session_id = new_id()
    workspace = await pool.prepare(ctx, session_id)
    assert workspace.location == "/workspace"
    (row,) = await pool.rows()
    assert (row.tenant_id, row.session_id, row.bound_by) == (ctx.org_id, session_id, ctx.user_id)
    assert row.name.startswith(PREFIX + "p") and row.host_id is not None
    assert row.key_digest is None and row.sealed_at is not None, "its key spent, then sealed"
    assert await pool.machines.state(row.name) is MachineState.RUNNING
    assert (pool.machines.root / row.name / "host-program").exists(), "the pool's image"
    (pooled,) = pool.placed.pools
    assert pooled is not None and pooled.pool is not None
    assert pooled.pool.session_id == session_id, "held in the session's pool of one"
    (admitted,) = pool.hosts.admitted
    assert admitted[2] == row.id, "enrolled with the machine its key was handed"

    seed = pool.seed(row.name)
    assert set(seed) == {"api_url", "key"}, "the seed holds where to call and the key, no more"
    with pytest.raises(InvalidCredential):
        await pool.manager.enroll(stage(), seed["key"], ENROLLMENT)
    with pytest.raises(InvalidCredential):
        await pool.manager.enroll(stage(), "hen_not-a-machine-key", ENROLLMENT)

    again = await pool.manager.prepare(ctx, session_id, OPEN)
    assert again.location == "/workspace"
    assert len(await pool.rows()) == 1, "the session's machine, found again"


async def test_a_new_session_claims_a_started_warm_machine_and_the_pool_starts_another(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, warm=1)
    await pool.image()
    assert await pool.manager.sweep(stage()) == 0
    await pool.manager.close()
    (warm,) = await pool.rows()
    assert warm.warm and warm.started_at is not None
    key = pool.seed(warm.name)["key"]
    with pytest.raises(MachineUnbound):
        await pool.manager.enroll(stage(), key, ENROLLMENT)

    session_id = new_id()
    await pool.prepare(ctx, session_id)
    await pool.manager.close()
    rows = await pool.rows()
    (claimed,) = [row for row in rows if row.session_id == session_id]
    assert claimed.id == warm.id, "the session claimed the machine started ahead"
    (replacement,) = [row for row in rows if row.warm]
    assert replacement.id != warm.id and replacement.started_at is not None
    assert await pool.machines.state(replacement.name) is MachineState.RUNNING
    assert await pool.manager.sweep(stage()) == 0
    await pool.manager.close()
    assert len(await pool.rows()) == 2, "the warm count stands; no more start"


# A snapshot is the machine's whole disk.


async def test_a_snapshot_ends_the_host_and_keeps_the_stopped_disk_which_a_restore_starts_from(
    pool: Pool, ctx: TenantContext
) -> None:
    session_id = new_id()
    await pool.prepare(ctx, session_id, KEPT)
    (row,) = await pool.rows()
    (pool.machines.root / row.name / "state.bin").write_text("built")
    handed = pool.seed(row.name)["key"]

    taken = await pool.manager.snapshot(ctx, session_id)
    assert taken.reference.startswith(snapshots_of(PREFIX, ctx.org_id, session_id))
    assert pool.hosts.retired == [row.host_id], "its credential ended before the disk was kept"
    assert await pool.machines.state(row.name) is MachineState.STOPPED, "kept until released"
    await pool.manager.release(ctx, session_id)
    assert await pool.machines.state(row.name) is MachineState.ABSENT
    assert await pool.rows() == []

    record = kept_record(session_id, taken.reference, taken.digest)
    await pool.prepare(ctx, session_id, KEPT, restore=record)
    (restored,) = await pool.rows()
    assert restored.restored_from == record.id and restored.name != row.name
    assert (pool.machines.root / restored.name / "state.bin").read_text() == "built"
    assert pool.seed(restored.name)["key"] != handed, "a machine started again takes a new key"

    # Asked again for the same restore, the machine it started stands.
    await pool.manager.prepare(ctx, session_id, KEPT, record)
    assert [r.id for r in await pool.rows()] == [restored.id]


async def test_a_restore_from_a_disk_gone_or_altered_loses_the_workspace(
    pool: Pool, ctx: TenantContext
) -> None:
    session_id = new_id()
    await pool.prepare(ctx, session_id, KEPT)
    taken = await pool.manager.snapshot(ctx, session_id)
    await pool.manager.release(ctx, session_id)

    altered = kept_record(session_id, taken.reference, "sha256:" + "1" * 64)
    with pytest.raises(WorkspaceLost, match="does not match its digest"):
        await pool.manager.prepare(ctx, session_id, KEPT, altered)
    await pool.machines.destroy(taken.reference)
    gone = kept_record(session_id, taken.reference, taken.digest)
    with pytest.raises(WorkspaceLost, match="gone"):
        await pool.manager.prepare(ctx, session_id, KEPT, gone)
    bucket = gone.model_copy(update={"machine": False, "digest": None})
    with pytest.raises(WorkspaceLost, match="not taken of a machine"):
        await pool.manager.prepare(ctx, session_id, KEPT, bucket)
    assert await pool.rows() == [], "nothing started"


async def test_a_snapshot_with_no_machine_is_refused(pool: Pool, ctx: TenantContext) -> None:
    with pytest.raises(SnapshotRefused):
        await pool.manager.snapshot(ctx, new_id())


# What the machines cannot hold is refused for good.


@pytest.mark.parametrize(
    ("spec", "why"),
    [
        (
            OPEN.model_copy(
                update={"egress": EgressPolicy(mode=EgressMode.ALLOWLIST, hosts=("pypi.org",))}
            ),
            "allowlist",
        ),
        (OPEN.model_copy(update={"egress": EgressPolicy(mode=EgressMode.NONE)}), "none"),
        (OPEN.model_copy(update={"limits": ResourceLimits(processes=10)}), "processes"),
        (
            OPEN.model_copy(
                update={
                    "base": WorkspaceBase(
                        image="python:3.14", egress=EgressPolicy(mode=EgressMode.OPEN)
                    )
                }
            ),
            "base",
        ),
        (OPEN.model_copy(update={"mode": IsolationMode.CONTAINER}), "container"),
    ],
)
async def test_a_spec_the_machines_cannot_hold_is_refused_for_good_before_any_start(
    pool: Pool, ctx: TenantContext, spec: IsolationSpec, why: str
) -> None:
    with pytest.raises(IsolationRefused, match=why) as refused:
        await pool.manager.prepare(ctx, new_id(), spec)
    assert not refused.value.clears
    assert await pool.rows() == []


async def test_a_backend_that_closes_egress_holds_a_session_that_reaches_nothing(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, closes_egress=True)
    await pool.image()
    closed = OPEN.model_copy(update={"egress": EgressPolicy(mode=EgressMode.NONE)})
    await pool.prepare(ctx, new_id(), closed)
    (row,) = await pool.rows()
    assert row.egress_open is False
    assert pool.machines.machines[row.name].spec.egress_open is False


# Every machine started is let go.


async def test_the_sweep_lets_go_of_a_dead_start_a_hostless_machine_a_gone_session_and_an_orphan(
    pool: Pool, ctx: TenantContext
) -> None:
    alive, gone = new_id(), new_id()
    await pool.prepare(ctx, alive)
    await pool.prepare(ctx, gone)
    pool.gone.add(gone)
    dead = PoolMachine(
        id=new_id(),
        created_at=pool.now - timedelta(minutes=20),
        name=f"{PREFIX}pdead0000000000000",
        egress_open=True,
    )
    await pool.storage.create_machine(dead)
    hostless = PoolMachine(
        id=new_id(),
        created_at=pool.now - timedelta(minutes=30),
        name=f"{PREFIX}phostless00000000",
        egress_open=True,
        tenant_id=ctx.org_id,
        session_id=new_id(),
        pool_id=new_id(),
        bound_by=ctx.user_id,
        started_at=pool.now - timedelta(minutes=30),
    )
    await pool.storage.create_machine(hostless)
    await pool.machines.launch(hostless.name, MachineSpec(image="twin", egress_open=True))
    orphan = f"{PREFIX}p0123456789abcdef"
    await pool.machines.launch(orphan, MachineSpec(image="twin", egress_open=True))
    vm_provider = f"{PREFIX}0123456789abcdef"  # the VM workspace provider's, not the pool's
    await pool.machines.launch(vm_provider, MachineSpec(image="twin", egress_open=True))

    assert await pool.manager.sweep(stage()) == 4
    left = await pool.rows()
    assert [row.session_id for row in left] == [alive]
    names = await pool.machines.names(PREFIX)
    assert sorted(names) == sorted([left[0].name, IMAGE, vm_provider])


async def test_a_purge_and_an_erase_take_the_sessions_disks_and_no_other_sessions(
    pool: Pool, ctx: TenantContext
) -> None:
    mine, theirs = new_id(), new_id()
    taken: dict[UUID, str] = {}
    for session_id in (mine, theirs):
        await pool.prepare(ctx, session_id, KEPT)
        taken[session_id] = (await pool.manager.snapshot(ctx, session_id)).reference
    await pool.manager.erase(ctx.org_id, mine)
    assert await pool.machines.state(taken[mine]) is MachineState.ABSENT
    assert await pool.machines.state(taken[theirs]) is MachineState.STOPPED
    assert len(await pool.rows()) == 2, "an erase keeps the machines, caches"

    await pool.manager.purge(ctx.org_id, mine)
    assert [row.session_id for row in await pool.rows()] == [theirs]
    assert await pool.machines.state(taken[theirs]) is MachineState.STOPPED


async def test_a_tenants_purge_waits_for_its_expiry_then_takes_every_machine_and_disk(
    pool: Pool, ctx: TenantContext
) -> None:
    other = context(Role.SERVICE, make_org())
    for tenant in (ctx, other):
        session_id = new_id()
        await pool.prepare(tenant, session_id, KEPT)
        await pool.manager.snapshot(tenant, session_id)
        await pool.prepare(tenant, new_id())
    assert await pool.manager.purge_tenant(ctx) == 0, "not past its retention"
    pool.expired_tenants.add(ctx.org_id)
    assert await pool.manager.purge_tenant(ctx) == 3
    assert {row.tenant_id for row in await pool.rows()} == {other.org_id}
    left = await pool.machines.names(PREFIX + "p")
    assert len(left) == 3, "the other tenant's two machines and its disk"
