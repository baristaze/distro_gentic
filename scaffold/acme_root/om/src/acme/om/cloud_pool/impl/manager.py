"""The cloud pool on the machines' backend. A row is written before its
machine starts and deleted once the machine is gone, so every machine under
the pool's names is accounted for by a row, or is let go by the sweep.

A start is inline for a session's prepare, bounded by the machines' own
boot bound, as the VM workspace provider's is; a warm machine starts in the
background, since nothing waits on it. Every path that starts a machine has
the one that lets it go: a session's snapshot, its release after the
grace, its purge, its tenant's purge, and the sweep, which lets go of a
start that died, a machine whose host never came, and a machine no row
holds."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field

from acme.infra.machines import MachinesInterface, MachineSpec, MachineState, SeedsInterface
from acme.infra.workspaces import (
    EgressMode,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    SnapshotRefused,
    Workspace,
    WorkspaceLost,
)
from acme.om.base import Platform, new_id, utcnow
from acme.om.cloud_pool.exceptions import MachineUnbound
from acme.om.cloud_pool.manager import CloudPoolManagerInterface
from acme.om.cloud_pool.rules import (
    KEY_PREFIX,
    MARK,
    is_snapshot,
    longest_name,
    machine_name,
    new_key,
    refusal,
    seed,
    snapshot_name,
    snapshots_of,
    tenant_snapshots,
)
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.types.machine import MachineSnapshot, PoolMachine
from acme.om.context import Permission, RequestContext, TenantContext
from acme.om.exceptions import InvalidCredential
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.types.credential import IssuedCredential
from acme.om.hosts.types.host import Enrollment
from acme.om.hosts.types.placement import PlacementState
from acme.om.hosts.types.pool import HostPool, Region
from acme.om.relay.manager import RelayManagerInterface
from acme.om.tenancy.rules import hash_token
from acme.om.workspaces.placed import PlacedWorkspacesInterface
from acme.om.workspaces.types.snapshot import KeptSnapshot

log = logging.getLogger(__name__)

SessionGone = Callable[[UUID, UUID], Awaitable[bool]]
"""Whether a tenant's session is gone, deleted or purged, or its tenant is:
given the tenant and the session."""


class CloudPoolOptions(Platform):
    # The machines' prefix, which the pool's names follow with its mark.
    prefix: str = Field(default="acme-vm-", min_length=1)
    # The snapshot of the machines' backend that holds the host program,
    # from which every new machine starts. Empty: the pool runs no machine.
    image: str = ""
    # What a machine made from nothing would boot, in the backend's terms;
    # the pool starts each machine from `image`, so this is the spec's alone.
    machine_image: str = Field(default="template:_images/ubuntu-lts", min_length=1)
    # The machines kept started ahead of demand. Autoscaling is not in it.
    warm: int = Field(default=0, ge=0)
    # The region a session's pool of one names.
    region: Region = "cloud"
    # Where the platform answers, as the pool's machines reach it.
    api_url: str = ""
    # How long a prepare waits for its machine's host to enroll and to
    # prepare the workspace before the loop waits on the resource.
    ready_wait: timedelta = Field(default=timedelta(minutes=3), gt=timedelta(0))
    # How long a machine may take to start: a start older than this with no
    # machine running died with the process that began it.
    boot: timedelta = Field(default=timedelta(minutes=15), gt=timedelta(0))
    # The most rows one pass of the sweep reads.
    max_machines: int = Field(default=1000, gt=0)
    first_poll: timedelta = Field(default=timedelta(milliseconds=200), gt=timedelta(0))
    last_poll: timedelta = Field(default=timedelta(seconds=2), gt=timedelta(0))


class CloudPoolManagerImpl(CloudPoolManagerInterface):
    """`hosts`, `placed`, and `relay` answer at call time, as the root builds
    them after the tools."""

    def __init__(
        self,
        storage: CloudPoolStorageInterface,
        machines: MachinesInterface,
        seeds: SeedsInterface,
        hosts: Callable[[], HostsManagerInterface],
        placed: Callable[[], PlacedWorkspacesInterface],
        relay: Callable[[], RelayManagerInterface],
        options: CloudPoolOptions,
        *,
        session_gone: SessionGone,
        expired: Callable[[TenantContext], Awaitable[bool]],
        stage: Callable[[], RequestContext],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._machines = machines
        self._seeds = seeds
        self._hosts = hosts
        self._placed = placed
        self._relay = relay
        self._options = options
        self._session_gone = session_gone
        self._expired = expired
        self._stage = stage
        self._sleep = sleep
        self._clock = clock
        self._starting: set[asyncio.Task[None]] = set()

    def runs(self, spec: IsolationSpec) -> bool:
        return bool(self._options.image) and spec.mode is IsolationMode.VM

    # A session's machine.

    async def prepare(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spec: IsolationSpec,
        restore: KeptSnapshot | None = None,
    ) -> Workspace:
        why = refusal(
            spec, closes_egress=self._machines.closes_egress(), limits=self._machines.limits()
        )
        if why is not None:
            raise IsolationRefused(why)
        if restore is not None and not restore.on_machines:
            raise WorkspaceLost(
                f"snapshot {restore.id} of session {session_id} was not taken of a machine "
                "of the cloud pool"
            )
        missing = await self._machines.probe(longest_name(self._options.prefix))
        if missing is not None:
            raise IsolationRefused(f"the cloud pool runs no machine here: {missing}")
        pool = await self._hosts().session_pool(ctx, session_id, self._options.region)
        machine = await self._machine_for(ctx, session_id, spec, pool, restore)
        machine = await self._enrolled(session_id, machine)
        if machine.sealed_at is None:
            await self._seeds.seal(machine.name)
            await self._storage.mark_sealed(machine.id, self._clock())
        return await self._held(ctx, session_id, spec, pool)

    async def snapshot(self, ctx: TenantContext, session_id: UUID) -> MachineSnapshot:
        machine = await self._storage.read_of_session(ctx.org_id, session_id)
        if machine is None or machine.started_at is None:
            raise SnapshotRefused(f"no machine of the cloud pool holds session {session_id}")
        # Ended first: the disk the snapshot keeps holds no credential that
        # answers.
        await self._retire(ctx, machine)
        await self._machines.stop(machine.name)
        to = snapshot_name(self._options.prefix, ctx.org_id, session_id)
        digest = await self._machines.snapshot(machine.name, to)
        log.info("session %s: machine %s kept as %s", session_id, machine.name, to)
        return MachineSnapshot(reference=to, digest=digest)

    async def holds(self, ctx: TenantContext, session_id: UUID) -> bool:
        return await self._storage.read_of_session(ctx.org_id, session_id) is not None

    async def release(self, ctx: TenantContext, session_id: UUID) -> None:
        machine = await self._storage.read_of_session(ctx.org_id, session_id)
        if machine is not None:
            await self._let_go(ctx, machine)

    async def purge(self, org_id: UUID, session_id: UUID) -> None:
        machine = await self._storage.read_of_session(org_id, session_id)
        if machine is not None:
            await self._let_go(self._stage(), machine)
        await self.erase(org_id, session_id)

    async def erase(self, org_id: UUID, session_id: UUID) -> None:
        named = snapshots_of(self._options.prefix, org_id, session_id)
        for name in await self._machines.names(named):
            await self._machines.destroy(name)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._expired(ctx):
            return 0
        gone = 0
        for machine in await self._storage.read_of_tenant(ctx.org_id, self._options.max_machines):
            await self._let_go(ctx, machine)
            gone += 1
        prefix = self._options.prefix
        for name in await self._machines.names(tenant_snapshots(prefix, ctx.org_id)):
            if is_snapshot(prefix, name):
                await self._machines.destroy(name)
                gone += 1
        return gone

    # A machine's host.

    async def enroll(
        self, rctx: RequestContext, key: str, enrollment: Enrollment
    ) -> IssuedCredential:
        if not key.startswith(KEY_PREFIX):
            raise InvalidCredential("a machine enrolls with the key it was handed")
        digest = hash_token(key)
        machine = await self._storage.read_by_key(digest)
        if machine is None:
            raise InvalidCredential("unknown or spent machine key")
        if machine.tenant_id is None or machine.pool_id is None or machine.bound_by is None:
            raise MachineUnbound(f"machine {machine.name} serves no session yet; ask again")
        if not await self._storage.spend_key(machine.id, digest):
            raise InvalidCredential("unknown or spent machine key")
        issued = await self._hosts().admit_machine(
            rctx,
            machine.tenant_id,
            machine.pool_id,
            machine.bound_by,
            machine.id,
            enrollment,
        )
        await self._storage.mark_enrolled(machine.id, issued.claimant_id)
        log.info(
            "machine %s: its host %s enrolled for session %s",
            machine.name,
            issued.claimant_id,
            machine.session_id,
        )
        return issued

    # The sweep.

    async def sweep(self, rctx: RequestContext) -> int:
        if not self._options.image:
            return 0
        now = self._clock()
        let_go = 0
        rows = await self._storage.read_machines(self._options.max_machines)
        for machine in rows:
            if await self._lost(machine, now):
                await self._let_go(rctx, machine)
                let_go += 1
        held = {machine.name for machine in rows}
        prefix = self._options.prefix
        for name in await self._machines.names(f"{prefix}{MARK}"):
            # A snapshot is kept under its session's names; a machine is not.
            if is_snapshot(prefix, name) or name == self._options.image or name in held:
                continue
            if await self._storage_holds_no(name):
                log.warning("machine %s is held by no row of the pool, and goes", name)
                await self._machines.destroy(name)
                let_go += 1
        await self._refill()
        return let_go

    async def close(self) -> None:
        if self._starting:
            await asyncio.gather(*self._starting, return_exceptions=True)

    # The parts.

    async def _machine_for(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spec: IsolationSpec,
        pool: HostPool,
        restore: KeptSnapshot | None,
    ) -> PoolMachine:
        """The machine that serves the session, running: the one it holds,
        unless a restore replaces it; else a warm one; else a new one."""
        current = await self._storage.read_of_session(ctx.org_id, session_id)
        if current is not None and restore is not None and current.restored_from != restore.id:
            # A restore replaces the machine whole.
            await self._let_go(ctx, current)
            current = None
        if current is not None:
            return await self._running(ctx, session_id, spec, current)
        if restore is not None:
            await self._held_to(session_id, restore)
            return await self._start(ctx, session_id, spec, pool, restore)
        egress_open = spec.egress.mode is EgressMode.OPEN
        if self._options.warm and not spec.limits.asked():
            claimed = await self._storage.claim_warm(
                ctx.org_id, session_id, pool.id, ctx.user_id, egress_open
            )
            if claimed is not None:
                log.info("session %s claimed warm machine %s", session_id, claimed.name)
                self._spawn(self._refill())
                return claimed
        return await self._start(ctx, session_id, spec, pool, None)

    async def _running(
        self, ctx: TenantContext, session_id: UUID, spec: IsolationSpec, machine: PoolMachine
    ) -> PoolMachine:
        """The session's machine, running. One still starting waits on the
        resource, unless its start died; one that stopped starts again under
        a new key, since its host's credential ended with it; one gone is
        forgotten, and another starts."""
        if machine.started_at is None:
            if self._clock() - machine.created_at < self._options.boot:
                raise IsolationRefused(
                    f"session {session_id}'s machine {machine.name} is starting", clears=True
                )
            await self._let_go(ctx, machine)
            raise IsolationRefused(
                f"session {session_id}'s machine {machine.name} did not start in time; "
                "another starts at the next ask",
                clears=True,
            )
        state = await self._machines.state(machine.name)
        if state is MachineState.RUNNING:
            return machine
        if state is MachineState.ABSENT:
            await self._let_go(ctx, machine)
            raise IsolationRefused(
                f"session {session_id}'s machine {machine.name} is gone; another starts at the "
                "next ask",
                clears=True,
            )
        await self._retire(ctx, machine)
        key = new_key()
        again = await self._storage.rekey(machine.id, hash_token(key), machine.restored_from)
        if again is None:
            raise IsolationRefused(f"session {session_id}'s machine is gone", clears=True)
        await self._seeds.launch_seeded(
            machine.name, self._spec(spec), None, seed(self._options.api_url, key)
        )
        await self._storage.mark_started(machine.id, self._clock())
        return again

    async def _start(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spec: IsolationSpec,
        pool: HostPool,
        restore: KeptSnapshot | None,
    ) -> PoolMachine:
        """A new machine for the session, from its snapshot or the pool's
        image. Its row is written first, so a start that dies leaves a row
        the sweep finds; one that fails here leaves nothing."""
        key = new_key()
        machine = PoolMachine(
            id=new_id(),
            created_at=self._clock(),
            name=machine_name(self._options.prefix),
            egress_open=spec.egress.mode is EgressMode.OPEN,
            tenant_id=ctx.org_id,
            session_id=session_id,
            pool_id=pool.id,
            bound_by=ctx.user_id,
            key_digest=hash_token(key),
            restored_from=None if restore is None else restore.id,
        )
        await self._storage.create_machine(machine)
        source = self._options.image if restore is None else restore.reference
        await self._launch(machine, self._spec(spec), source, key)
        log.info("session %s: machine %s started from %s", session_id, machine.name, source)
        return machine

    async def _launch(self, machine: PoolMachine, spec: MachineSpec, source: str, key: str) -> None:
        """Starts the machine its row names, handed its key, and marks it
        started; one that fails goes with its row."""
        try:
            await self._seeds.launch_seeded(
                machine.name, spec, source, seed(self._options.api_url, key)
            )
        except BaseException:
            try:
                await self._machines.destroy(machine.name)
            finally:
                await self._storage.delete_machine(machine.id)
            raise
        await self._storage.mark_started(machine.id, self._clock())

    async def _enrolled(self, session_id: UUID, machine: PoolMachine) -> PoolMachine:
        """The machine once its host has enrolled, waited on a while."""
        by = self._clock() + self._options.ready_wait
        wait = self._options.first_poll
        while True:
            found = await self._storage.read_machine(machine.id)
            if found is None:
                raise IsolationRefused(
                    f"session {session_id}'s machine {machine.name} is gone", clears=True
                )
            if found.host_id is not None:
                return found
            left = (by - self._clock()).total_seconds()
            if left <= 0:
                raise IsolationRefused(
                    f"session {session_id}'s machine {machine.name} runs, and its host has not "
                    "enrolled yet",
                    clears=True,
                )
            await self._sleep(min(wait.total_seconds(), left))
            wait = min(wait * 2, self._options.last_poll)

    async def _held(
        self, ctx: TenantContext, session_id: UUID, spec: IsolationSpec, pool: HostPool
    ) -> Workspace:
        """The workspace once the machine's host holds it, waited on a while:
        its host is asked to prepare it through the relay, as any host is."""
        by = self._clock() + self._options.ready_wait
        wait = self._options.first_poll
        while True:
            hosts = await self._hosts().get_hosts(ctx, pool.id)
            placed = PlacementState(
                session_id=session_id,
                pool=pool,
                hosts_online=sum(1 for status in hosts if status.online),
            )
            try:
                held = await self._placed().held_on_host(ctx, session_id, spec, pooled=placed)
            except IsolationRefused as refused:
                if not refused.clears or self._clock() >= by:
                    raise
            else:
                assert held is not None  # a pool of one is given
                return held
            left = (by - self._clock()).total_seconds()
            await self._sleep(max(0.0, min(wait.total_seconds(), left)))
            wait = min(wait * 2, self._options.last_poll)

    async def _held_to(self, session_id: UUID, restore: KeptSnapshot) -> None:
        """The snapshot's disk, held to the digest the pool recorded, before
        anything starts from it: one gone or altered loses the workspace."""
        digest = await self._machines.digest(restore.reference)
        if digest is None:
            raise WorkspaceLost(
                f"snapshot {restore.id} of session {session_id} is gone from the machines' store"
            )
        if digest != restore.digest:
            raise WorkspaceLost(
                f"snapshot {restore.id} of session {session_id} does not match its digest"
            )

    async def _let_go(self, rctx: RequestContext, machine: PoolMachine) -> None:
        """The machine goes: its host's credential ends, then the machine and
        its disk, then its row."""
        await self._retire(rctx, machine)
        await self._machines.destroy(machine.name)
        await self._storage.delete_machine(machine.id)
        log.info("machine %s of session %s let go", machine.name, machine.session_id)

    async def _retire(self, rctx: RequestContext, machine: PoolMachine) -> None:
        if machine.host_id is not None and machine.tenant_id is not None:
            by = machine.bound_by or machine.host_id
            await self._hosts().retire_host(rctx, machine.tenant_id, machine.host_id, by)

    async def _lost(self, machine: PoolMachine, now: datetime) -> bool:
        """Whether the sweep lets a machine go: a start older than the boot
        bound that never ran; a session's machine whose host has not
        enrolled within the boot bound and the wait after it; or one whose
        session, or tenant, is gone."""
        if machine.started_at is None:
            return now - machine.created_at > self._options.boot
        if machine.tenant_id is None or machine.session_id is None:
            return False
        if machine.host_id is None and (
            now - machine.started_at > self._options.boot + self._options.ready_wait
        ):
            return True
        return await self._session_gone(machine.tenant_id, machine.session_id)

    async def _storage_holds_no(self, name: str) -> bool:
        """Read again just before a destroy: a start writes its row before
        its machine, so a machine whose row the pass did not read may have
        one now."""
        rows = await self._storage.read_machines(self._options.max_machines)
        return all(row.name != name for row in rows)

    async def _refill(self) -> None:
        """Starts warm machines, in the background, until the warm count
        stands."""
        wanted = self._options.warm
        if not wanted or not self._options.image:
            return
        keys = [new_key() for _ in range(wanted)]
        egress_open = not self._machines.closes_egress()
        made = [
            PoolMachine(
                id=new_id(),
                created_at=self._clock(),
                name=machine_name(self._options.prefix),
                egress_open=egress_open,
                key_digest=hash_token(key),
            )
            for key in keys
        ]
        written = await self._storage.reserve_warm(wanted, made)
        if not written:
            return
        spec = MachineSpec(image=self._options.machine_image, egress_open=egress_open)
        for machine, key in zip(made[:written], keys[:written], strict=True):
            self._spawn(self._warm(machine, spec, key))
        log.info("the cloud pool starts %d warm machines", written)

    async def _warm(self, machine: PoolMachine, spec: MachineSpec, key: str) -> None:
        try:
            await self._launch(machine, spec, self._options.image, key)
        except Exception:
            log.exception("warm machine %s did not start, and is let go", machine.name)

    def _spawn(self, work: Awaitable[None]) -> None:
        task = asyncio.ensure_future(work)
        self._starting.add(task)
        task.add_done_callback(self._starting.discard)

    def _spec(self, spec: IsolationSpec) -> MachineSpec:
        cpus = spec.limits.cpus
        return MachineSpec(
            image=self._options.machine_image,
            cpus=None if cpus is None else int(cpus),
            memory_mb=spec.limits.memory_mb,
            egress_open=spec.egress.mode is EgressMode.OPEN,
        )
