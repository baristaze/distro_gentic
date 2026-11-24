"""The cloud pool over the VMs' twin: a VM per session, started
from the pool's image, handed a one-use key its host trades once for a
credential of the session's pool of one. A warm VM serves no session
until one claims it, and the pool starts another in its place. Every VM
starts from the pool's image, and none's disk is kept: a restore lets go
of a VM that serves the session for another snapshot, marks the one that
serves it next, a warm one claimed included, and keeps it while it starts.
A spec the VMs cannot hold is refused for good, a size the deployment
does not allow among them; a VM is the machine type its size maps to,
and a warm one the default size's. A cold start records its boot once, a
warm claim none. Each claim counts once, by how it got its VM, a prepare
asked again before it returned counting none, and records its wait once,
as its prepare returns, never at a command; a restore is timed by
its archive's size in a few classes. A VM past its maximum age goes between runs and never
under a running loop, and a warm one past it goes at the sweep. The sweep reads every
row, a page at a time: it lets go of a first start that died, one whose
session is gone, and one no row holds, and stops a VM that runs with
no host to work for, whose disk its session's next prepare starts again; a
VM started again keeps its disk through a sweep and a failed start. A
purge, an erase, and a tenant's purge take the record of the session's
archives, and no other session's; an erase does so in a process that
reaches no VM too. The claim and the sweep never race: a claimed VM's host is asked
for the session's workspace only once it enrolled and its VM is sealed, and
the session has none until its host holds it; a warm VM a session claims
while the sweep reads it as a dead start stays the session's; and a VM
that dies after its host enrolled is let go at the next sweep, as a warm
one that dies is."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from prometheus_client import REGISTRY

from acme.infra.agent_workspaces import (
    AgentWorkspace,
    AgentWorkspaceBase,
    Durability,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    ResourceLimits,
    VmSize,
)
from acme.infra.impl.local import InfraLocalImpl
from acme.infra.transports import CommandResult, CommandSpec, OutputSink, RecordSeal
from acme.infra.transports.twin import TransportNullImpl
from acme.infra.vms import SEED_FILE, MachineType, VmSpec, VmState
from acme.infra.vms.seeded import PLAIN_WRITE, SeedsChannelImpl
from acme.infra.vms.twin import VmsNullImpl, VmsTwinImpl
from acme.om.base import new_id, utcnow
from acme.om.cloud_pool.exceptions import VmUnbound
from acme.om.cloud_pool.impl.manager import CloudPoolManagerImpl, CloudPoolOptions
from acme.om.cloud_pool.rules import MIB, archive_size, new_key, seed
from acme.om.cloud_pool.storage.impl.memory import CloudPoolStorageMemoryImpl
from acme.om.cloud_pool.types.sizes import PoolSizes
from acme.om.cloud_pool.types.vm import ClaimSource, PoolVm
from acme.om.context import AppContext, AppType, RequestContext, Role, TenantContext
from acme.om.exceptions import InvalidCredential
from acme.om.exec_relay.impl.transport import TransportPlacedImpl
from acme.om.hosts.types.credential import IssuedCredential
from acme.om.hosts.types.host import Advertisement, Enrollment, HostStatus
from acme.om.hosts.types.host import IsolationMode as HostMode
from acme.om.hosts.types.placement import PlacementState
from acme.om.hosts.types.pool import HostPool
from acme.om.platform_root import PlatformRootOptions, build_platform_managers
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tenancy.rules import hash_token

from contracts.agent_session_storage import stored_session
from contracts.doubles import context
from contracts.factories import make_org

PREFIX = "acme-vm-"
IMAGE = "acme-vm-image"
OPEN = IsolationSpec(mode=IsolationMode.VM, egress=EgressPolicy(mode=EgressMode.OPEN))
KEPT = OPEN.model_copy(update={"durability": Durability.SNAPSHOT})
MEDIUM = OPEN.model_copy(update={"limits": ResourceLimits(size=VmSize.M)})
ENROLLMENT = Enrollment(
    name="vm",
    advertisement=Advertisement(os="Linux", isolation_modes=(HostMode.VM,)),
    exec_version=2,
)


def stage() -> RequestContext:
    return RequestContext(request_id=new_id(), app=AppContext(type=AppType.WORKER, version="t"))


@dataclass
class Seen:
    """A VM's host as the pool reads it: when it last called, and when
    its credential ended."""

    last_seen_at: datetime
    revoked_at: datetime | None = None


class Hosts:
    """What the pool asks of the hosts: a session's pool of one, a VM's
    host admitted into it, read, and its credential ended."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self.admitted: list[tuple[UUID, UUID, UUID]] = []  # host, pool, VM row
        self.retired: list[UUID] = []
        self.seen: dict[UUID, Seen] = {}
        self._clock = clock

    async def session_pool(
        self, ctx: TenantContext, agent_session_id: UUID, region: str
    ) -> HostPool:
        now = utcnow()
        return HostPool(
            id=UUID(int=agent_session_id.int ^ 1),
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            name=f"cloud-{agent_session_id}",
            region=region,
            agent_session_id=agent_session_id,
        )

    async def admit_vm(
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

    async def vm_host(self, rctx: RequestContext, org_id: UUID, host_id: UUID) -> Seen | None:
        return self.seen.get(host_id)

    async def get_hosts(self, ctx: TenantContext, pool_id: UUID) -> tuple[HostStatus, ...]:
        return ()


class Placed:
    """The relay's side of a prepare: the workspace the VM's host holds,
    in the session's pool of one."""

    def __init__(self) -> None:
        self.pools: list[PlacementState | None] = []

    async def held_on_host(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        restore: object = None,
        *,
        pooled: PlacementState | None = None,
    ) -> AgentWorkspace:
        self.pools.append(pooled)
        return AgentWorkspace(
            id=agent_session_id, org_id=ctx.org_id, spec=spec, location="/workspace"
        )


class Pool:
    def __init__(
        self,
        root: Path,
        *,
        warm: int = 0,
        closes_egress: bool = False,
        page: int = 1000,
        most: int | None = None,
        tenant_most: int | None = None,
        sizes: PoolSizes | None = None,
    ) -> None:
        # Only the limits a test names, so the options' own stand otherwise.
        named = {"most": most, "tenant_most": tenant_most, "sizes": sizes}
        limits: dict[str, Any] = {key: value for key, value in named.items() if value is not None}
        self.vms = VmsTwinImpl(root / "vms", closes_egress=closes_egress)
        self.storage = CloudPoolStorageMemoryImpl()
        self.now = utcnow()
        self.hosts = Hosts(lambda: self.now)
        self.placed = Placed()
        self.gone: set[UUID] = set()
        self.dropped: list[UUID] = []  # the sessions whose archives went
        self.options = CloudPoolOptions(
            prefix=PREFIX,
            image=IMAGE,
            warm=warm,
            api_url="http://gateway.test",
            ready_wait=timedelta(seconds=5),
            boot=timedelta(minutes=15),
            silent=timedelta(minutes=15),
            page=page,
            **limits,
            first_poll=timedelta(milliseconds=5),
            last_poll=timedelta(milliseconds=20),
        )
        self.manager = self.built(self.vms)
        self.expired_tenants: set[UUID] = set()

    def built(self, vms: VmsTwinImpl | VmsNullImpl) -> CloudPoolManagerImpl:
        """The pool as a process builds it on these VMs, over the same
        rows: the API's process reaches none."""
        return CloudPoolManagerImpl(
            self.storage,
            vms,
            SeedsChannelImpl(vms, timedelta(seconds=10), PLAIN_WRITE),
            lambda: cast(Any, self.hosts),
            lambda: cast(Any, self.placed),
            lambda: cast(Any, None),
            self.options,
            session_gone=self.session_gone,
            expired=self.expired,
            active_at=self.active_at,
            drop_archives=self.drop_archives,
            stage=stage,
            clock=lambda: self.now,
        )

    async def session_gone(self, org_id: UUID, agent_session_id: UUID) -> bool:
        return agent_session_id in self.gone

    async def expired(self, ctx: TenantContext) -> bool:
        return ctx.org_id in self.expired_tenants

    async def active_at(self, org_id: UUID, agent_session_id: UUID) -> datetime | None:
        return None if agent_session_id in self.gone else self.now

    async def drop_archives(self, org_id: UUID, agent_session_id: UUID) -> None:
        self.dropped.append(agent_session_id)

    async def image(self) -> None:
        """The pool's image: a stopped VM that holds the host program."""
        await self.vms.launch(IMAGE, VmSpec(image="twin", egress_open=True))
        (self.vms.root / IMAGE / "host-program").write_text("the host")
        await self.vms.stop(IMAGE)

    def seed(self, name: str) -> dict[str, Any]:
        loaded = json.loads((self.vms.root / name / SEED_FILE).read_text())
        assert isinstance(loaded, dict)
        return cast(dict[str, Any], loaded)

    async def rows(self) -> list[PoolVm]:
        return await self.storage.read_vms(100)

    async def host_comes(self, agent_session_id: UUID | None = None) -> UUID:
        """Plays the VM's host: once a VM that serves the session
        runs with the seed of its latest start, it trades the key there."""
        while True:
            for row in await self.rows():
                if (agent_session_id is None or row.agent_session_id == agent_session_id) and (
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
        agent_session_id: UUID,
        spec: IsolationSpec = OPEN,
        restore: UUID | None = None,
    ) -> AgentWorkspace:
        host = asyncio.ensure_future(self.host_comes(agent_session_id))
        try:
            return await self.manager.prepare(ctx, agent_session_id, spec, restore)
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


# A VM per session, and its host.


async def test_a_session_gets_a_vm_from_the_pools_image_whose_host_trades_its_key_once(
    pool: Pool, ctx: TenantContext
) -> None:
    agent_session_id = new_id()
    workspace = await pool.prepare(ctx, agent_session_id)
    assert workspace.location == "/workspace"
    (row,) = await pool.rows()
    assert (row.tenant_id, row.agent_session_id, row.bound_by) == (
        ctx.org_id,
        agent_session_id,
        ctx.user_id,
    )
    assert row.name.startswith(PREFIX + "p") and row.host_id is not None
    assert row.key_digest is None and row.sealed_at is not None, "its key spent, then sealed"
    assert await pool.vms.state(row.name) is VmState.RUNNING
    assert (pool.vms.root / row.name / "host-program").exists(), "the pool's image"
    (pooled,) = pool.placed.pools
    assert pooled is not None and pooled.pool is not None
    assert pooled.pool.agent_session_id == agent_session_id, "held in the session's pool of one"
    (admitted,) = pool.hosts.admitted
    assert admitted[2] == row.id, "enrolled with the VM its key was handed"

    seed = pool.seed(row.name)
    assert set(seed) == {"api_url", "key"}, "the seed holds where to call and the key, no more"
    with pytest.raises(InvalidCredential):
        await pool.manager.enroll(stage(), seed["key"], ENROLLMENT)
    with pytest.raises(InvalidCredential):
        await pool.manager.enroll(stage(), "hen_not-a-vm-key", ENROLLMENT)

    again = await pool.manager.prepare(ctx, agent_session_id, OPEN)
    assert again.location == "/workspace"
    assert len(await pool.rows()) == 1, "the session's VM, found again"


async def test_a_new_session_claims_a_started_warm_vm_and_the_pool_starts_another(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, warm=1)
    await pool.image()
    assert await pool.manager.sweep(stage()) == 0
    await pool.manager.close()
    (warm,) = await pool.rows()
    assert warm.warm and warm.started_at is not None
    key = pool.seed(warm.name)["key"]
    with pytest.raises(VmUnbound):
        await pool.manager.enroll(stage(), key, ENROLLMENT)

    agent_session_id = new_id()
    await pool.prepare(ctx, agent_session_id)
    await pool.manager.close()
    rows = await pool.rows()
    (claimed,) = [row for row in rows if row.agent_session_id == agent_session_id]
    assert claimed.id == warm.id, "the session claimed the VM started ahead"
    (replacement,) = [row for row in rows if row.warm]
    assert replacement.id != warm.id and replacement.started_at is not None
    assert await pool.vms.state(replacement.name) is VmState.RUNNING
    assert await pool.manager.sweep(stage()) == 0
    await pool.manager.close()
    assert len(await pool.rows()) == 2, "the warm count stands; no more start"


# A VM is the size its spec asks, as the deployment maps it.


async def test_a_spec_asking_m_gets_a_vm_of_the_type_its_deployment_maps_m_to(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, warm=1)
    await pool.image()
    await pool.manager.sweep(stage())
    await pool.manager.close()
    (warm,) = await pool.rows()
    small = pool.options.sizes.s
    assert pool.vms.vms[warm.name].spec.machine_type == small.name, "warm at the default size"

    agent_session_id = new_id()
    await pool.prepare(ctx, agent_session_id, MEDIUM)
    (row,) = [row for row in await pool.rows() if row.agent_session_id == agent_session_id]
    assert row.id != warm.id, "a warm VM serves the default size alone"
    started = pool.vms.vms[row.name].spec
    medium = pool.options.sizes.m
    assert medium is not None
    assert (started.machine_type, started.cpus, started.memory_mb) == (
        medium.name,
        medium.cpus,
        medium.memory_mb,
    )
    assert (await pool.storage.read_vm(warm.id)) == warm, "the warm VM still stands"


async def test_a_size_the_deployment_does_not_allow_is_refused_for_good_before_any_start(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, sizes=PoolSizes(s=MachineType(name="m7g.large", cpus=2, memory_mb=8192)))
    await pool.image()
    made = len(pool.vms.calls)
    with pytest.raises(IsolationRefused) as refused:
        await pool.manager.prepare(ctx, new_id(), MEDIUM)
    assert not refused.value.clears
    assert refused.value.cause == "the cloud pool runs no VM of size m here"
    assert await pool.rows() == [] and len(pool.vms.calls) == made, "no VM started"


# A cold start is timed, from its start to its host's enrollment.


def boots() -> tuple[float, float]:
    """The boots the process recorded: how many, and their seconds
    together."""
    name = "acme_cloud_pool_boot_seconds"
    count = REGISTRY.get_sample_value(f"{name}_count") or 0.0
    total = REGISTRY.get_sample_value(f"{name}_sum") or 0.0
    return count, total


async def test_a_cold_start_records_one_boot_from_its_start_to_enrollment_and_a_warm_claim_none(
    tmp_path: Path, ctx: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = Pool(tmp_path, warm=1)
    await pool.image()
    before = boots()
    launch = pool.vms.launch

    async def booting(name: str, spec: VmSpec, snapshot: str | None = None) -> None:
        await launch(name, spec, snapshot)
        pool.now += timedelta(seconds=42)  # it boots, and then its host calls

    monkeypatch.setattr(pool.vms, "launch", booting)
    await pool.prepare(ctx, new_id())
    monkeypatch.undo()
    assert boots() == (before[0] + 1, before[1] + 42), "one boot, start to enrollment"

    await pool.manager.sweep(stage())
    await pool.manager.close()
    pool.now += timedelta(minutes=5)
    claimed = new_id()
    await pool.prepare(ctx, claimed)
    await pool.manager.close()
    (row,) = [row for row in await pool.rows() if row.agent_session_id == claimed]
    assert row.host_id is not None and row.bound_at is not None
    assert row.created_at < row.bound_at, "a warm VM, claimed"
    assert boots() == (before[0] + 1, before[1] + 42), "a warm claim records none"


# Each claim counts once, by how it got its VM, and waits for its prepare.


def claims() -> dict[str, float]:
    """The claims the process counted, by source."""
    name = "acme_cloud_pool_claims_total"
    return {
        source.value: REGISTRY.get_sample_value(name, {"source": source.value}) or 0.0
        for source in ClaimSource
    }


def counted_since(before: dict[str, float]) -> dict[str, float]:
    """The claims counted since `before`, by source, where any were."""
    now = claims()
    return {source: now[source] - before[source] for source in now if now[source] != before[source]}


async def test_a_warm_claim_a_new_vm_a_held_one_and_one_started_again_each_count_once(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, warm=1)
    await pool.image()
    await pool.manager.sweep(stage())
    await pool.manager.close()
    holding = Holding(pool)
    pool.placed = holding

    before = claims()
    waited = waits(ClaimSource.WARM)
    warm = new_id()
    with pytest.raises(IsolationRefused):
        await pool.prepare(ctx, warm)
    assert waits(ClaimSource.WARM) == waited, "no wait until a prepare returns"
    holding.holds = True
    await pool.prepare(ctx, warm)
    await pool.manager.close()
    assert counted_since(before) == {"warm": 1}, "a claim asked again before it returned is one"
    assert waits(ClaimSource.WARM) == (waited[0] + 1, waited[1] + 10), "its wait, across the asks"

    before = claims()
    session = new_id()
    await pool.prepare(ctx, session, MEDIUM)
    assert counted_since(before) == {"new": 1}, "no warm VM of its size: a new one"

    before = claims()
    await pool.prepare(ctx, session, MEDIUM)
    assert counted_since(before) == {"held": 1}, "its next loop finds the one it held"

    before = claims()
    (row,) = [row for row in await pool.rows() if row.agent_session_id == session]
    await pool.vms.stop(row.name)
    await pool.prepare(ctx, session, MEDIUM)
    (again,) = [row for row in await pool.rows() if row.agent_session_id == session]
    assert again.id == row.id
    assert counted_since(before) == {"restarted": 1}, "the one it held, started again"


class Ran(TransportNullImpl):
    """The relay's side of a command: each one run, at once."""

    def __init__(self) -> None:
        self.commands: list[CommandSpec] = []

    async def run(
        self,
        workspace: AgentWorkspace,
        command: CommandSpec,
        on_output: OutputSink | None = None,
        *,
        seal: RecordSeal,
    ) -> CommandResult:
        self.commands.append(command)
        return CommandResult(key=command.key, exit_code=0)


async def _unread(data: bytes) -> bytes | None:
    return None


def waits(source: ClaimSource) -> tuple[float, float]:
    """The claims' waits the process recorded under `source`: how many, and
    their seconds together."""
    name = "acme_cloud_pool_claim_wait_seconds"
    labels = {"source": source.value}
    count = REGISTRY.get_sample_value(f"{name}_count", labels) or 0.0
    total = REGISTRY.get_sample_value(f"{name}_sum", labels) or 0.0
    return count, total


async def test_a_claim_records_its_wait_once_as_its_prepare_returns_never_at_a_command(
    pool: Pool, ctx: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A kind that prepares early claims its VM beside its run's first model
    call, so its first command may come long after the prepare returned.
    The wait is the prepare's time, from the claim to the workspace handed
    over, and the model's turns before the command are no part of it."""
    ran = Ran()
    # The runner's transport: a session of the pool's commands go to its VM.
    placed = TransportPlacedImpl(TransportNullImpl(), ran, cast(Any, None), pool.manager.runs)
    seal = RecordSeal(seal=_unread, open=_unread)
    launch = pool.vms.launch

    async def booting(name: str, spec: VmSpec, snapshot: str | None = None) -> None:
        await launch(name, spec, snapshot)
        pool.now += timedelta(seconds=12)  # it boots, and then its host calls

    monkeypatch.setattr(pool.vms, "launch", booting)
    before = waits(ClaimSource.NEW)
    workspace = await pool.prepare(ctx, new_id())
    monkeypatch.undo()
    assert waits(ClaimSource.NEW) == (before[0] + 1, before[1] + 12), "the prepare's time"

    for seconds in (300, 30):  # the model's turns, then its commands
        pool.now += timedelta(seconds=seconds)
        command = CommandSpec(argv=("true",), key=new_id(), epoch=0, deadline=pool.now)
        await placed.run(workspace, command, seal=seal)

    assert len(ran.commands) == 2
    assert waits(ClaimSource.NEW) == (before[0] + 1, before[1] + 12), "once, and no command's"


def test_an_archive_is_timed_under_one_of_a_few_size_classes() -> None:
    assert archive_size(0) == "under_10mib"
    assert archive_size(10 * MIB - 1) == "under_10mib"
    assert archive_size(10 * MIB) == "under_100mib"
    assert archive_size(1024 * MIB - 1) == "under_1gib"
    assert archive_size(1024 * MIB) == archive_size(4 * 1024 * MIB) == "1gib_and_over"


# A VM is recycled at its maximum age, between runs.


async def test_a_vm_past_its_age_goes_between_runs_never_under_a_loop_and_another_starts(
    pool: Pool, ctx: TenantContext
) -> None:
    agent_session_id = new_id()
    await pool.prepare(ctx, agent_session_id)
    (old,) = await pool.rows()
    assert not await pool.manager.recycle(ctx, agent_session_id), "under its age it stays"

    pool.now += pool.options.max_age + timedelta(minutes=1)
    assert old.host_id is not None
    pool.hosts.seen[old.host_id].last_seen_at = pool.now  # its loop runs, and its host calls
    assert await pool.manager.sweep(stage()) == 0, "no sweep lets it go under a running loop"
    assert await pool.rows() == [old] and await pool.vms.state(old.name) is VmState.RUNNING

    assert await pool.manager.recycle(ctx, agent_session_id), "its run's end lets it go"
    assert await pool.rows() == [] and await pool.vms.state(old.name) is VmState.ABSENT
    assert pool.hosts.retired == [old.host_id], "its host's credential ended first"

    await pool.prepare(ctx, agent_session_id)
    (new,) = await pool.rows()
    assert new.id != old.id and new.name != old.name and new.created_at == pool.now
    assert (pool.vms.root / new.name / "host-program").exists(), "from the pool's image"


async def test_a_warm_vm_past_its_age_goes_at_the_sweep_and_another_stands(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, warm=1)
    await pool.image()
    await pool.manager.sweep(stage())
    await pool.manager.close()
    (old,) = await pool.rows()

    pool.now += pool.options.max_age + timedelta(minutes=1)
    assert await pool.manager.sweep(stage()) == 1
    await pool.manager.close()
    (new,) = await pool.rows()
    assert new.warm and new.id != old.id and new.started_at is not None
    assert await pool.vms.state(old.name) is VmState.ABSENT


# A restore replaces the VM whole, from the pool's image; no disk is kept.


async def test_a_restore_replaces_the_sessions_vm_with_one_from_the_image_kept_while_it_starts(
    pool: Pool, ctx: TenantContext
) -> None:
    agent_session_id = new_id()
    await pool.prepare(ctx, agent_session_id, KEPT)
    (row,) = await pool.rows()
    (pool.vms.root / row.name / "state.bin").write_text("built")
    handed = pool.seed(row.name)["key"]
    snapshot_id = new_id()

    await pool.prepare(ctx, agent_session_id, KEPT, restore=snapshot_id)
    (restored,) = await pool.rows()
    assert restored.restored_from == snapshot_id and restored.name != row.name
    assert pool.hosts.retired == [row.host_id], "the VM it replaced was let go"
    assert await pool.vms.state(row.name) is VmState.ABSENT
    assert not (pool.vms.root / restored.name / "state.bin").exists(), "nothing of its disk"
    assert (pool.vms.root / restored.name / "host-program").exists(), "from the pool's image"
    assert pool.seed(restored.name)["key"] != handed

    # Asked again for the same restore, the VM it started stands.
    await pool.manager.prepare(ctx, agent_session_id, KEPT, snapshot_id)
    assert [r.id for r in await pool.rows()] == [restored.id]
    await pool.manager.release(ctx, agent_session_id)
    assert await pool.vms.names(PREFIX) == [IMAGE], "no disk of any VM is kept"
    assert not [call for call in pool.vms.calls if call[0] == "snapshot"]


async def test_a_restore_claims_a_warm_vm_since_every_vm_starts_from_the_image(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, warm=1)
    await pool.image()
    await pool.manager.sweep(stage())
    await pool.manager.close()
    (warm,) = await pool.rows()
    agent_session_id, snapshot_id = new_id(), new_id()

    await pool.prepare(ctx, agent_session_id, KEPT, restore=snapshot_id)
    await pool.manager.close()

    mine = [row for row in await pool.rows() if row.agent_session_id == agent_session_id]
    assert [(row.id, row.restored_from) for row in mine] == [(warm.id, snapshot_id)]


# What the VMs cannot hold is refused for good.


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
        (OPEN.model_copy(update={"limits": ResourceLimits(cpus=2, size=VmSize.M)}), "cpus"),
        (
            OPEN.model_copy(
                update={
                    "base": AgentWorkspaceBase(
                        image="python:3.14", egress=EgressPolicy(mode=EgressMode.OPEN)
                    )
                }
            ),
            "base",
        ),
        (OPEN.model_copy(update={"mode": IsolationMode.CONTAINER}), "container"),
    ],
)
async def test_a_spec_the_vms_cannot_hold_is_refused_for_good_before_any_start(
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
    assert pool.vms.vms[row.name].spec.egress_open is False


# Every VM started is let go.


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
    await pool.storage.create_vm(dead)
    hostless = PoolVm(
        id=new_id(),
        created_at=pool.now - timedelta(minutes=30),
        name=f"{PREFIX}phostless00000000",
        egress_open=True,
        tenant_id=ctx.org_id,
        agent_session_id=new_id(),
        pool_id=new_id(),
        bound_by=ctx.user_id,
        started_at=pool.now - timedelta(minutes=30),
    )
    await pool.storage.create_vm(hostless)
    await pool.vms.launch(hostless.name, VmSpec(image="twin", egress_open=True))
    orphan = f"{PREFIX}p0123456789abcdef"
    await pool.vms.launch(orphan, VmSpec(image="twin", egress_open=True))
    vm_provider = f"{PREFIX}0123456789abcdef"  # the VM workspace provider's, not the pool's
    await pool.vms.launch(vm_provider, VmSpec(image="twin", egress_open=True))

    assert await pool.manager.sweep(stage()) == 4
    left = {row.agent_session_id: row for row in await pool.rows()}
    assert set(left) == {alive, hostless.agent_session_id}
    assert await pool.vms.state(hostless.name) is VmState.STOPPED, "its disk kept"
    names = await pool.vms.names(PREFIX)
    assert sorted(names) == sorted([left[alive].name, hostless.name, IMAGE, vm_provider])


async def test_the_sweep_reads_every_row_a_page_at_a_time_and_takes_no_vm_a_row_holds(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, page=1)
    await pool.image()
    sessions = [new_id() for _ in range(3)]
    for agent_session_id in sessions:
        await pool.prepare(ctx, agent_session_id)
    pool.gone.add(sessions[2])
    assert await pool.manager.sweep(stage()) == 1, "the gone session's VM, whatever its page"
    left = await pool.rows()
    assert {row.agent_session_id for row in left} == set(sessions[:2])
    for row in left:
        assert await pool.vms.state(row.name) is VmState.RUNNING
    await pool.manager.close()


async def test_a_sweep_mid_restart_and_after_a_failed_one_keeps_the_vm_and_its_disk(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path)
    await pool.image()
    agent_session_id = new_id()
    await pool.prepare(ctx, agent_session_id, KEPT)
    (row,) = await pool.rows()
    work = pool.vms.root / row.name / "state.bin"
    work.write_text("unpushed work")
    await pool.vms.stop(row.name)  # the cloud stopped it; hours pass
    pool.now = pool.now + timedelta(hours=2)
    seeds = pool.manager._seeds  # pyright: ignore[reportPrivateUsage]
    real = seeds.launch_seeded
    swept: list[int] = []

    async def fails_after_a_sweep(*args: Any, **kwargs: Any) -> None:
        swept.append(await pool.manager.sweep(stage()))
        raise RuntimeError("a start that fails")

    seeds.launch_seeded = fails_after_a_sweep  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await pool.prepare(ctx, agent_session_id, KEPT)
    pool.now = pool.now + timedelta(hours=1)
    swept.append(await pool.manager.sweep(stage()))
    assert swept == [0, 0], "neither mid start nor after a failed one"
    assert work.read_text() == "unpushed work"

    async def starts_after_a_sweep(*args: Any, **kwargs: Any) -> None:
        swept.append(await pool.manager.sweep(stage()))
        await real(*args, **kwargs)

    seeds.launch_seeded = starts_after_a_sweep  # type: ignore[method-assign]
    await pool.prepare(ctx, agent_session_id, KEPT)
    assert swept == [0, 0, 0]
    (again,) = await pool.rows()
    assert again.id == row.id and again.host_id is not None and again.host_id != row.host_id
    assert await pool.vms.state(row.name) is VmState.RUNNING
    assert work.read_text() == "unpushed work", "the next ask finds the disk it left"
    await pool.manager.close()


async def test_a_vm_whose_host_ended_or_went_silent_is_stopped_and_started_again_on_its_disk(
    pool: Pool, ctx: TenantContext
) -> None:
    ended, silent = new_id(), new_id()
    for agent_session_id in (ended, silent):
        await pool.prepare(ctx, agent_session_id, KEPT)
    rows = {row.agent_session_id: row for row in await pool.rows()}
    ended_host, silent_host = rows[ended].host_id, rows[silent].host_id
    assert ended_host is not None and silent_host is not None
    work = pool.vms.root / rows[ended].name / "work.txt"
    work.write_text("kept")
    # One host's credential is ended under it; the other exits and calls no
    # more, as a host that never probed does.
    pool.hosts.seen[ended_host].revoked_at = pool.now
    pool.now = pool.now + timedelta(minutes=10)
    assert await pool.manager.sweep(stage()) == 1
    assert await pool.vms.state(rows[ended].name) is VmState.STOPPED
    assert await pool.vms.state(rows[silent].name) is VmState.RUNNING, "not silent yet"
    pool.now = pool.now + timedelta(minutes=10)
    assert await pool.manager.sweep(stage()) == 1
    assert await pool.vms.state(rows[silent].name) is VmState.STOPPED
    assert silent_host in pool.hosts.retired, "its credential ends as it stops"
    assert await pool.manager.sweep(stage()) == 0, "a stopped VM bills no compute"
    assert len(await pool.rows()) == 2, "and stays for its session"

    await pool.prepare(ctx, ended, KEPT)
    (again,) = [row for row in await pool.rows() if row.agent_session_id == ended]
    assert again.id == rows[ended].id and again.host_id not in (None, ended_host)
    assert await pool.vms.state(again.name) is VmState.RUNNING
    assert work.read_text() == "kept"


async def test_a_warm_vm_claimed_after_standing_long_waits_for_its_host_from_the_claim(
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

    async def swept_before_the_host(agent_session_id: UUID, vm: PoolVm) -> PoolVm:
        swept.append(await pool.manager.sweep(stage()))
        return await real(agent_session_id, vm)

    pool.manager._enrolled = swept_before_the_host  # type: ignore[method-assign]
    agent_session_id = new_id()
    await pool.prepare(ctx, agent_session_id)
    await pool.manager.close()
    claimed = await pool.storage.read_vm(warm.id)
    assert swept == [0], "a sweep before its host enrolls leaves it be"
    assert claimed is not None and claimed.agent_session_id == agent_session_id
    assert claimed.bound_at == pool.now and claimed.host_id is not None
    assert await pool.vms.state(warm.name) is VmState.RUNNING


async def test_an_erase_in_a_process_that_reaches_no_vm_forgets_the_sessions_archives(
    pool: Pool, ctx: TenantContext
) -> None:
    agent_session_id = new_id()
    await pool.prepare(ctx, agent_session_id, KEPT)
    await pool.manager.archived(ctx, agent_session_id)
    api = pool.built(VmsNullImpl())  # the API's process reaches no VM
    await api.erase(ctx.org_id, agent_session_id)
    await api.erase(ctx.org_id, agent_session_id)  # asked again, as every revocation call does
    assert await pool.storage.read_archives(pool.now + timedelta(days=365), 10) == []
    assert len(await pool.rows()) == 1, "its VM, a cache, stays"


async def test_a_deleted_tenants_vm_goes_at_the_next_sweep(tmp_path: Path) -> None:
    storage = StorageMemoryImpl()
    infra = InfraLocalImpl(tmp_path)
    managers = build_platform_managers(
        storage,
        infra,
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
        session = stored_session()
        await storage.get_agent_session_storage().create_agent_session(org.id, session, ())
        now = utcnow()
        held[org.name] = PoolVm(
            id=new_id(),
            created_at=now,
            name=f"{PREFIX}p{org.name.lower()}",
            egress_open=True,
            tenant_id=org.id,
            agent_session_id=session.id,
            pool_id=new_id(),
            bound_by=new_id(),
            started_at=now,
            bound_at=now,
        )
        await rows.create_vm(held[org.name])
        await infra.get_vms().launch(held[org.name].name, VmSpec(image="twin", egress_open=True))
    gone = deleted.model_copy(update={"deleted_at": utcnow(), "deleted_by": deleted.id})
    await orgs.write_org(deleted.id, gone)
    assert await managers.cloud_pool.sweep(stage()) == 1, "its session still stands"
    assert [row.id for row in await rows.read_vms(10)] == [held["Kept"].id]


async def test_a_purge_and_an_erase_take_the_sessions_archives_and_no_other_sessions(
    pool: Pool, ctx: TenantContext
) -> None:
    mine, theirs = new_id(), new_id()
    for agent_session_id in (mine, theirs):
        await pool.prepare(ctx, agent_session_id, KEPT)
        await pool.manager.archived(ctx, agent_session_id)
    later = pool.now + timedelta(days=365)
    await pool.manager.erase(ctx.org_id, mine)
    assert [a.agent_session_id for a in await pool.storage.read_archives(later, 10)] == [theirs]
    assert len(await pool.rows()) == 2, "an erase keeps the VMs, caches"

    await pool.manager.archived(ctx, mine)
    await pool.manager.purge(ctx.org_id, mine)
    assert [row.agent_session_id for row in await pool.rows()] == [theirs]
    assert [a.agent_session_id for a in await pool.storage.read_archives(later, 10)] == [theirs]


async def test_a_tenants_purge_waits_for_its_expiry_then_takes_every_vm_and_archive(
    pool: Pool, ctx: TenantContext
) -> None:
    other = context(Role.SERVICE, make_org())
    for tenant in (ctx, other):
        agent_session_id = new_id()
        await pool.prepare(tenant, agent_session_id, KEPT)
        await pool.manager.archived(tenant, agent_session_id)
        await pool.prepare(tenant, new_id())
    assert await pool.manager.purge_tenant(ctx) == 0, "not past its retention"
    pool.expired_tenants.add(ctx.org_id)
    assert await pool.manager.purge_tenant(ctx) == 3, "its two VMs and its archives' record"
    assert {row.tenant_id for row in await pool.rows()} == {other.org_id}
    kept = await pool.storage.read_archives(pool.now + timedelta(days=365), 10)
    assert [archive.tenant_id for archive in kept] == [other.org_id]
    assert len(await pool.vms.names(PREFIX + "p")) == 2, "the other tenant's two VMs"


# The claim and the sweep never race.


class Holding(Placed):
    """The relay's side, which reads the session's VM as its host is asked
    for the workspace, and holds none until told to."""

    def __init__(self, pool: Pool) -> None:
        super().__init__()
        self.pool = pool
        self.holds = False
        self.asked: list[PoolVm] = []

    async def held_on_host(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        restore: object = None,
        *,
        pooled: PlacementState | None = None,
    ) -> AgentWorkspace:
        rows = await self.pool.rows()
        self.asked.extend(row for row in rows if row.agent_session_id == agent_session_id)
        if not self.holds:
            self.pool.now = self.pool.now + timedelta(seconds=10)  # its wait runs out
            raise IsolationRefused("its host holds no workspace yet", clears=True)
        return await super().held_on_host(ctx, agent_session_id, spec, restore, pooled=pooled)


async def test_a_claimed_vms_host_is_asked_for_the_workspace_only_once_enrolled_and_sealed(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, warm=1)
    await pool.image()
    await pool.manager.sweep(stage())
    await pool.manager.close()
    (warm,) = await pool.rows()
    holding = Holding(pool)
    pool.placed = holding
    agent_session_id = new_id()
    with pytest.raises(IsolationRefused) as waiting:
        await pool.prepare(ctx, agent_session_id)
    assert waiting.value.clears, "no workspace until its host holds one: the loop waits"
    (asked,) = holding.asked
    assert asked.id == warm.id, "the warm VM it claimed"
    assert asked.host_id is not None, "its host enrolled before it was asked"
    assert asked.sealed_at is not None, "and its VM was sealed"
    holding.holds = True
    workspace = await pool.prepare(ctx, agent_session_id)
    assert workspace.location == "/workspace"
    await pool.manager.close()


async def test_a_warm_vm_a_session_claims_while_the_sweep_reads_it_is_never_destroyed_under_it(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, warm=1)
    await pool.image()
    key = new_key()
    late = PoolVm(
        id=new_id(),
        created_at=pool.now - timedelta(minutes=20),
        name=f"{PREFIX}plate000000000000",
        egress_open=True,
        key_digest=hash_token(key),
    )
    await pool.storage.create_vm(late)
    seeds = pool.manager._seeds  # pyright: ignore[reportPrivateUsage]
    await seeds.launch_seeded(
        late.name, VmSpec(image="twin", egress_open=True), IMAGE, seed(pool.options.api_url, key)
    )
    # A warm start past the boot bound, which the sweep reads as dead: it
    # runs just after the sweep's read, and a session claims it before the
    # sweep acts.
    agent_session_id = new_id()
    real = pool.storage.read_vms
    raced: list[UUID] = []

    async def claimed_after_the_read(limit: int, after: UUID | None = None) -> list[PoolVm]:
        page = await real(limit, after)
        if not raced:
            raced.append(late.id)
            await pool.storage.mark_started(late.id, pool.now)
            await pool.prepare(ctx, agent_session_id)
        return page

    pool.storage.read_vms = claimed_after_the_read  # type: ignore[method-assign]
    await pool.manager.sweep(stage())
    await pool.manager.close()
    pool.storage.read_vms = real  # type: ignore[method-assign]
    held = await pool.storage.read_of_session(ctx.org_id, agent_session_id)
    assert held is not None and held.id == late.id, "the session claimed the warm VM"
    assert await pool.vms.state(late.name) is VmState.RUNNING, "and keeps it"


async def test_a_vm_that_dies_after_its_host_enrolled_is_let_go_at_the_next_sweep(
    tmp_path: Path, ctx: TenantContext
) -> None:
    pool = Pool(tmp_path, warm=1)
    await pool.image()
    await pool.manager.sweep(stage())
    await pool.manager.close()
    agent_session_id = new_id()
    await pool.prepare(ctx, agent_session_id)
    await pool.manager.close()
    rows = await pool.rows()
    (bound,) = [row for row in rows if row.agent_session_id == agent_session_id]
    (warm,) = [row for row in rows if row.warm]
    assert bound.host_id is not None and warm.started_at is not None
    # The cloud takes both VMs away; the session's host called a moment ago.
    await pool.vms.destroy(bound.name)
    await pool.vms.destroy(warm.name)
    assert await pool.manager.sweep(stage()) == 2
    await pool.manager.close()
    assert bound.host_id in pool.hosts.retired, "its host's credential ended"
    (replacement,) = await pool.rows()
    assert replacement.id not in (bound.id, warm.id), "neither holds a place any more"
    assert replacement.warm and replacement.started_at is not None, "the warm count stands again"
    assert await pool.vms.state(replacement.name) is VmState.RUNNING
