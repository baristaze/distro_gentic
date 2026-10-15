"""The cloud pool over the machines' twin: a machine per session, started
from the pool's image, handed a one-use key its host trades once for a
credential of the session's pool of one. A warm machine serves no session
until one claims it, and the pool starts another in its place. A snapshot
ends the host's credential, stops the machine, and keeps its disk; a
restore holds the disk to its digest and starts a machine on a copy of it.
A spec the machines cannot hold is refused for good. The sweep reads every
row, a page at a time: it lets go of a first start that died, one whose
session is gone, and one no row holds, and stops a machine that runs with
no host to work for, whose disk its session's next prepare starts again; a
machine started again keeps its disk through a sweep and a failed start. A
purge, an erase, and a tenant's purge take the session's disks, and no
other session's; an erase asked where no machine is reached is done by the
sweep."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from contracts.doubles import context
from contracts.factories import make_org

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.machines import SEED_FILE, MachineSpec, MachineState
from acme.infra.machines.seeded import PLAIN_WRITE, SeedsChannelImpl
from acme.infra.machines.twin import MachinesNullImpl, MachinesTwinImpl
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
from acme.om.agent_workspaces.types.snapshot import KeptSnapshot
from acme.om.base import new_id, utcnow
from acme.om.cloud_pool.exceptions import MachineUnbound
from acme.om.cloud_pool.impl.manager import CloudPoolManagerImpl, CloudPoolOptions
from acme.om.cloud_pool.rules import snapshots_of
from acme.om.cloud_pool.storage.impl.memory import CloudPoolStorageMemoryImpl
from acme.om.cloud_pool.types.machine import PoolVm
from acme.om.context import AppContext, AppType, RequestContext, Role, TenantContext
from acme.om.exceptions import InvalidCredential
from acme.om.hosts.types.credential import IssuedCredential
from acme.om.hosts.types.host import Advertisement, Enrollment, HostStatus
from acme.om.hosts.types.host import IsolationMode as HostMode
from acme.om.hosts.types.placement import PlacementState
from acme.om.hosts.types.pool import HostPool
from acme.om.platform_root import PlatformRootOptions, build_platform_managers
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tenancy.rules import hash_token

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


@dataclass
class Seen:
    """A machine's host as the pool reads it: when it last called, and when
    its credential ended."""

    last_seen_at: datetime
    revoked_at: datetime | None = None


class Hosts:
    """What the pool asks of the hosts: a session's pool of one, a machine's
    host admitted into it, read, and its credential ended."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self.admitted: list[tuple[UUID, UUID, UUID]] = []  # host, pool, machine row
        self.retired: list[UUID] = []
        self.seen: dict[UUID, Seen] = {}
        self._clock = clock

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
        self.seen[host_id] = Seen(last_seen_at=self._clock())
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
        if host_id in self.seen and self.seen[host_id].revoked_at is None:
            self.seen[host_id].revoked_at = self._clock()

    async def machine_host(self, rctx: RequestContext, org_id: UUID, host_id: UUID) -> Seen | None:
        return self.seen.get(host_id)

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
    def __init__(
        self, root: Path, *, warm: int = 0, closes_egress: bool = False, page: int = 1000
    ) -> None:
        self.machines = MachinesTwinImpl(root / "machines", closes_egress=closes_egress)
        self.storage = CloudPoolStorageMemoryImpl()
        self.now = utcnow()
        self.hosts = Hosts(lambda: self.now)
        self.placed = Placed()
        self.gone: set[UUID] = set()
        self.options = CloudPoolOptions(
            prefix=PREFIX,
            image=IMAGE,
            warm=warm,
            api_url="http://gateway.test",
            ready_wait=timedelta(seconds=5),
            boot=timedelta(minutes=15),
            silent=timedelta(minutes=15),
            page=page,
            first_poll=timedelta(milliseconds=5),
            last_poll=timedelta(milliseconds=20),
        )
        self.manager = self.built(self.machines)
        self.expired_tenants: set[UUID] = set()

    def built(self, machines: MachinesTwinImpl | MachinesNullImpl) -> CloudPoolManagerImpl:
        """The pool as a process builds it on these machines, over the same
        rows: the API's process reaches none."""
        return CloudPoolManagerImpl(
            self.storage,
            machines,
            SeedsChannelImpl(machines, timedelta(seconds=10), PLAIN_WRITE),
            lambda: cast(Any, self.hosts),
            lambda: cast(Any, self.placed),
            lambda: cast(Any, None),
            self.options,
            session_gone=self.session_gone,
            expired=self.expired,
            stage=stage,
            clock=lambda: self.now,
        )

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

    async def rows(self) -> list[PoolVm]:
        return await self.storage.read_machines(100)

    async def host_comes(self, session_id: UUID | None = None) -> UUID:
        """Plays the machine's host: once a machine that serves the session
        runs with the seed of its latest start, it trades the key there."""
        while True:
            for row in await self.rows():
                if (session_id is None or row.session_id == session_id) and (
                    row.started_at is not None and row.key_digest is not None
                ):
                    key = self.seed(row.name)["key"]
                    if hash_token(key) != row.key_digest:
                        continue  # started again, and its new seed not handed yet
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


async def test_the_sweep_lets_go_of_a_dead_start_a_gone_session_and_an_orphan_and_stops_the_hostless(
    pool: Pool, ctx: TenantContext
) -> None:
    alive, gone = new_id(), new_id()
    await pool.prepare(ctx, alive)
    await pool.prepare(ctx, gone)
    pool.gone.add(gone)
    dead = PoolVm(
        id=new_id(),
        created_at=pool.now - timedelta(minutes=20),
        name=f"{PREFIX}pdead0000000000000",
        egress_open=True,
    )
    await pool.storage.create_machine(dead)
    hostless = PoolVm(
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
    left = {row.session_id: row for row in await pool.rows()}
    assert set(left) == {alive, hostless.session_id}
    assert await pool.machines.state(hostless.name) is MachineState.STOPPED, "its disk kept"
    names = await pool.machines.names(PREFIX)
    assert sorted(names) == sorted([left[alive].name, hostless.name, IMAGE, vm_provider])


async def test_the_sweep_reads_every_row_a_page_at_a_time_and_takes_no_machine_a_row_holds(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, page=1)
    await pool.image()
    sessions = [new_id() for _ in range(3)]
    for session_id in sessions:
        await pool.prepare(ctx, session_id)
    pool.gone.add(sessions[2])
    assert await pool.manager.sweep(stage()) == 1, "the gone session's machine, whatever its page"
    left = await pool.rows()
    assert {row.session_id for row in left} == set(sessions[:2])
    for row in left:
        assert await pool.machines.state(row.name) is MachineState.RUNNING
    await pool.manager.close()


async def test_a_sweep_mid_restart_and_after_a_failed_one_keeps_the_machine_and_its_disk(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path)
    await pool.image()
    session_id = new_id()
    await pool.prepare(ctx, session_id, KEPT)
    (row,) = await pool.rows()
    work = pool.machines.root / row.name / "state.bin"
    work.write_text("unpushed work")
    await pool.machines.stop(row.name)  # the cloud stopped it; hours pass
    pool.now = pool.now + timedelta(hours=2)
    seeds = pool.manager._seeds  # pyright: ignore[reportPrivateUsage]
    real = seeds.launch_seeded
    swept: list[int] = []

    async def fails_after_a_sweep(*args: Any, **kwargs: Any) -> None:
        swept.append(await pool.manager.sweep(stage()))
        raise RuntimeError("a start that fails")

    seeds.launch_seeded = fails_after_a_sweep  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await pool.prepare(ctx, session_id, KEPT)
    pool.now = pool.now + timedelta(hours=1)
    swept.append(await pool.manager.sweep(stage()))
    assert swept == [0, 0], "neither mid start nor after a failed one"
    assert work.read_text() == "unpushed work"

    async def starts_after_a_sweep(*args: Any, **kwargs: Any) -> None:
        swept.append(await pool.manager.sweep(stage()))
        await real(*args, **kwargs)

    seeds.launch_seeded = starts_after_a_sweep  # type: ignore[method-assign]
    await pool.prepare(ctx, session_id, KEPT)
    assert swept == [0, 0, 0]
    (again,) = await pool.rows()
    assert again.id == row.id and again.host_id is not None and again.host_id != row.host_id
    assert await pool.machines.state(row.name) is MachineState.RUNNING
    assert work.read_text() == "unpushed work", "the next ask finds the disk it left"
    await pool.manager.close()


async def test_a_machine_whose_host_ended_or_went_silent_is_stopped_and_started_again_on_its_disk(
    pool: Pool, ctx: TenantContext
) -> None:
    ended, silent = new_id(), new_id()
    for session_id in (ended, silent):
        await pool.prepare(ctx, session_id, KEPT)
    rows = {row.session_id: row for row in await pool.rows()}
    ended_host, silent_host = rows[ended].host_id, rows[silent].host_id
    assert ended_host is not None and silent_host is not None
    work = pool.machines.root / rows[ended].name / "work.txt"
    work.write_text("kept")
    # One host's credential is ended under it; the other exits and calls no
    # more, as a host that never probed does.
    pool.hosts.seen[ended_host].revoked_at = pool.now
    pool.now = pool.now + timedelta(minutes=10)
    assert await pool.manager.sweep(stage()) == 1
    assert await pool.machines.state(rows[ended].name) is MachineState.STOPPED
    assert await pool.machines.state(rows[silent].name) is MachineState.RUNNING, "not silent yet"
    pool.now = pool.now + timedelta(minutes=10)
    assert await pool.manager.sweep(stage()) == 1
    assert await pool.machines.state(rows[silent].name) is MachineState.STOPPED
    assert silent_host in pool.hosts.retired, "its credential ends as it stops"
    assert await pool.manager.sweep(stage()) == 0, "a stopped machine bills no compute"
    assert len(await pool.rows()) == 2, "and stays for its session"

    await pool.prepare(ctx, ended, KEPT)
    (again,) = [row for row in await pool.rows() if row.session_id == ended]
    assert again.id == rows[ended].id and again.host_id not in (None, ended_host)
    assert await pool.machines.state(again.name) is MachineState.RUNNING
    assert work.read_text() == "kept"


async def test_a_warm_machine_claimed_after_standing_long_waits_for_its_host_from_the_claim(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, warm=1)
    await pool.image()
    await pool.manager.sweep(stage())
    await pool.manager.close()
    (warm,) = await pool.rows()
    pool.now = pool.now + timedelta(minutes=30)  # it stood warm half an hour
    swept: list[int] = []
    real = pool.manager._enrolled  # pyright: ignore[reportPrivateUsage]

    async def swept_before_the_host(session_id: UUID, machine: PoolVm) -> PoolVm:
        swept.append(await pool.manager.sweep(stage()))
        return await real(session_id, machine)

    pool.manager._enrolled = swept_before_the_host  # type: ignore[method-assign]
    session_id = new_id()
    await pool.prepare(ctx, session_id)
    await pool.manager.close()
    claimed = await pool.storage.read_machine(warm.id)
    assert swept == [0], "a sweep before its host enrolls leaves it be"
    assert claimed is not None and claimed.session_id == session_id
    assert claimed.bound_at == pool.now and claimed.host_id is not None
    assert await pool.machines.state(warm.name) is MachineState.RUNNING


async def test_an_erase_asked_where_no_machine_is_reached_is_done_by_the_sweep(
    pool: Pool, ctx: TenantContext
) -> None:
    session_id = new_id()
    await pool.prepare(ctx, session_id, KEPT)
    taken = (await pool.manager.snapshot(ctx, session_id)).reference
    api = pool.built(MachinesNullImpl())  # the API's process reaches no machine
    await api.erase(ctx.org_id, session_id)
    await api.erase(ctx.org_id, session_id)  # asked again, as every revocation call does
    assert await pool.machines.state(taken) is MachineState.STOPPED
    assert len(await pool.storage.read_erasures(10)) == 1
    await pool.manager.sweep(stage())
    assert await pool.machines.state(taken) is MachineState.ABSENT
    assert await pool.storage.read_erasures(10) == []


async def test_a_deleted_tenants_machine_goes_at_the_next_sweep(tmp_path: Path) -> None:
    storage = StorageMemoryImpl()
    managers = build_platform_managers(
        storage,
        InfraLocalImpl(tmp_path),
        platform_root_options=PlatformRootOptions(
            cloud_pool_options=CloudPoolOptions(prefix=PREFIX, image=IMAGE),
            cloud_pool_stage=stage,
        ),
    )
    orgs, rows = storage.get_tenancy_storage(), storage.get_cloud_pool_storage()
    held: dict[str, PoolVm] = {}
    deleted = make_org("Deleted")
    for org in (deleted, make_org("Kept")):
        await orgs.write_org(org.id, org)
        session = make_session()
        await storage.get_agent_session_storage().create_session(org.id, session, ())
        now = utcnow()
        held[org.name] = PoolVm(
            id=new_id(),
            created_at=now,
            name=f"{PREFIX}p{org.name.lower()}",
            egress_open=True,
            tenant_id=org.id,
            session_id=session.id,
            pool_id=new_id(),
            bound_by=new_id(),
            started_at=now,
            bound_at=now,
        )
        await rows.create_machine(held[org.name])
    gone = deleted.model_copy(update={"deleted_at": utcnow(), "deleted_by": deleted.id})
    await orgs.write_org(deleted.id, gone)
    assert await managers.cloud_pool.sweep(stage()) == 1, "its session still stands"
    assert [row.id for row in await rows.read_machines(10)] == [held["Kept"].id]


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
