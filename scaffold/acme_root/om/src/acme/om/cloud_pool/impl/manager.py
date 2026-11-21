"""The cloud pool on the VMs' backend. A row is written before its
VM starts and deleted once the VM is gone, so every VM under
the pool's names is accounted for by a row, or is let go by the sweep;
a warm VM's row goes first, under the lock its claims take, so no claim
binds a VM being destroyed.

Every claim and every refill reads the pool's limits, which its operators
write: the warm VMs, the most VMs the pool holds at once, and the most one
tenant holds, its own where an operator set one. A claim past either
maximum starts no VM: the session's loop waits on the resource and asks
again, told no count and no other tenant's use.

A VM is the size its session's spec asks by name, which the
deployment's map turns into a machine type; a warm VM is the default
size. A start is inline for a session's prepare, bounded by the VMs' own
boot bound, as the VM workspace provider's is; a warm VM starts in the
background, since nothing waits on it. A cold start's boot, from its start
to its host's enrollment, is a metric; a warm claim records none. Every path that starts a VM has
the one that lets it go: a session's snapshot, its release after the
grace, its purge, its tenant's purge, and the sweep, which lets go of a
start that never ran, of a VM whose session or tenant is gone, and of
a VM no row holds. A VM that ran keeps its disk until its session
lets it go: the sweep stops one that runs with no host to work for, and its
session's next prepare starts it again under a new key. A VM past its
maximum age goes between runs, once its run's end kept its work, never
under a running loop; a warm one past it goes at the sweep."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.infra.agent_workspaces import (
    AgentWorkspace,
    AgentWorkspaceLost,
    EgressMode,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    SnapshotRefused,
    VmSize,
)
from acme.infra.exceptions import InfraException
from acme.infra.observability import CLOUD_POOL_BOOT_SECONDS
from acme.infra.vms import SeedsInterface, VmsInterface, VmSpec, VmState
from acme.om.agent_workspaces.placed import PlacedWorkspacesInterface
from acme.om.agent_workspaces.types.snapshot import KeptSnapshot
from acme.om.base import EMPTY_UUID, OmBase, new_id, utcnow
from acme.om.cloud_pool.exceptions import VmUnbound
from acme.om.cloud_pool.manager import CloudPoolManagerInterface
from acme.om.cloud_pool.rules import (
    DEFAULT_SIZE,
    KEY_PREFIX,
    MARK,
    is_snapshot,
    longest_name,
    new_key,
    refusal,
    seed,
    size_of,
    snapshot_name,
    snapshots_of,
    tenant_snapshots,
    vm_name,
)
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.types.erasure import PoolErasure
from acme.om.cloud_pool.types.limits import MOST_VMS, Full, PoolLimits
from acme.om.cloud_pool.types.sizes import SIZES, PoolSizes
from acme.om.cloud_pool.types.vm import PoolVm, VmSnapshot
from acme.om.context import Permission, RequestContext, TenantContext
from acme.om.exceptions import InvalidCredential
from acme.om.exec_relay.manager import ExecRelayManagerInterface
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.types.credential import IssuedCredential
from acme.om.hosts.types.host import Enrollment
from acme.om.hosts.types.placement import PlacementState
from acme.om.hosts.types.pool import HostPool, Region
from acme.om.tenancy.rules import hash_token
from acme.timing import Retries, RetryPolicy

log = logging.getLogger(__name__)

FULL_CAUSES = {
    Full.POOL: "no VM of the cloud pool is free yet",
    Full.TENANT: "this tenant holds as many VMs of the cloud pool as it may at once",
}
"""What a session's park says when a maximum holds its claim: never a
count, and never another tenant's use."""

SessionGone = Callable[[UUID, UUID], Awaitable[bool]]
"""Whether a tenant's session is gone, deleted or purged, or its tenant is:
given the tenant and the session."""


class CloudPoolOptions(OmBase):
    # The VMs' prefix, which the pool's names follow with its mark.
    prefix: str = Field(default="acme-vm-", min_length=1)
    # The snapshot of the VMs' backend that holds the host program,
    # from which every new VM starts. Empty: the pool runs no VM.
    image: str = ""
    # What a VM made from nothing would boot, in the backend's terms;
    # the pool starts each VM from `image`, so this is the spec's alone.
    vm_image: str = Field(default="template:_images/ubuntu-lts", min_length=1)
    # The pool's limits where no operator wrote them: the VMs kept started
    # ahead of demand, the most VMs the pool holds at once, and the most one
    # tenant holds. Autoscaling is not in it.
    warm: int = Field(default=0, ge=0, le=MOST_VMS)
    most: int = Field(default=20, ge=0, le=MOST_VMS)
    tenant_most: int = Field(default=5, ge=0, le=MOST_VMS)
    # Each size a session's spec may ask by name, and the machine it starts:
    # the deployment's map, whose types are the only ones its role may
    # launch. A size it does not name is refused for good.
    sizes: PoolSizes = SIZES
    # How long a VM serves its session across runs: past it, its run's end
    # lets it go, its work kept, and the next loop starts another.
    max_age: timedelta = Field(default=timedelta(hours=72), gt=timedelta(0))
    # The region a session's pool of one names.
    region: Region = "cloud"
    # Where the platform answers, as the pool's VMs reach it.
    api_url: str = ""
    # How long a prepare waits for its VM's host to enroll and to
    # prepare the workspace before the loop waits on the resource.
    ready_wait: timedelta = Field(default=timedelta(minutes=3), gt=timedelta(0))
    # How long a VM may take to start: a start older than this with no
    # VM running died with the process that began it.
    boot: timedelta = Field(default=timedelta(minutes=15), gt=timedelta(0))
    # How long a VM's host may go without a call before the sweep stops
    # its VM: it exited, or its credential was ended.
    silent: timedelta = Field(default=timedelta(minutes=15), gt=timedelta(0))
    # The rows the sweep, and a tenant's purge, read at a time.
    page: int = Field(default=1000, gt=0)
    first_poll: timedelta = Field(default=timedelta(milliseconds=200), gt=timedelta(0))
    last_poll: timedelta = Field(default=timedelta(seconds=2), gt=timedelta(0))

    @model_validator(mode="after")
    def _warm_below_most(self) -> Self:
        if self.warm and self.warm >= self.most:
            raise ValueError("the warm VMs stand below the most the pool holds")
        return self


def standing_limits(
    written: PoolLimits | None, options: CloudPoolOptions, at: datetime
) -> PoolLimits:
    """The pool's limits as a claim reads them: the operators' last write,
    else its options', as version 0, which no person wrote."""
    if written is not None:
        return written
    return PoolLimits(
        id=EMPTY_UUID,
        created_at=at,
        updated_at=at,
        created_by=EMPTY_UUID,
        updated_by=EMPTY_UUID,
        warm=options.warm,
        most=options.most,
        tenant_most=options.tenant_most,
        version=0,
    )


class CloudPoolManagerImpl(CloudPoolManagerInterface):
    """`hosts`, `placed`, and `exec_relay` answer at call time, as the root builds
    them after the tools."""

    def __init__(
        self,
        storage: CloudPoolStorageInterface,
        vms: VmsInterface,
        seeds: SeedsInterface,
        hosts: Callable[[], HostsManagerInterface],
        placed: Callable[[], PlacedWorkspacesInterface],
        exec_relay: Callable[[], ExecRelayManagerInterface],
        options: CloudPoolOptions,
        *,
        session_gone: SessionGone,
        expired: Callable[[TenantContext], Awaitable[bool]],
        stage: Callable[[], RequestContext] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._vms = vms
        self._seeds = seeds
        self._hosts = hosts
        self._placed = placed
        self._exec_relay = exec_relay
        self._options = options
        self._poll = RetryPolicy(
            base=options.first_poll.total_seconds(), cap=options.last_poll.total_seconds()
        )
        self._session_gone = session_gone
        self._expired = expired
        self._stage = stage
        self._sleep = sleep
        self._clock = clock
        self._starting: set[asyncio.Task[None]] = set()

    async def runs(self, spec: IsolationSpec) -> bool:
        return bool(self._options.image) and spec.mode is IsolationMode.VM

    # A session's VM.

    async def prepare(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        restore: KeptSnapshot | None = None,
    ) -> AgentWorkspace:
        why = refusal(
            spec, closes_egress=self._vms.closes_egress(), sizes=self._options.sizes.allowed()
        )
        if why is not None:
            # Composed from what the spec declares: the session reads it.
            raise IsolationRefused(why, cause=why)
        if restore is not None and not restore.on_vms:
            raise AgentWorkspaceLost(
                f"snapshot {restore.id} of session {agent_session_id} was not taken of a VM "
                "of the cloud pool"
            )
        missing = await self._vms.probe(longest_name(self._options.prefix))
        if missing is not None:
            raise IsolationRefused(f"the cloud pool runs no VM here: {missing}")
        pool = await self._hosts().session_pool(ctx, agent_session_id, self._options.region)
        vm = await self._vm_for(ctx, agent_session_id, spec, pool, restore)
        vm = await self._enrolled(agent_session_id, vm)
        if vm.sealed_at is None:
            await self._seeds.seal(vm.name)
            await self._storage.mark_sealed(vm.id, self._clock())
        return await self._held(ctx, agent_session_id, spec, pool)

    async def snapshot(self, ctx: TenantContext, agent_session_id: UUID) -> VmSnapshot:
        vm = await self._storage.read_of_session(ctx.org_id, agent_session_id)
        if vm is None or vm.started_at is None:
            raise SnapshotRefused(f"no VM of the cloud pool holds session {agent_session_id}")
        # Ended first: the disk the snapshot keeps holds no credential that
        # answers.
        await self._retire(ctx, vm)
        await self._vms.stop(vm.name)
        to = snapshot_name(self._options.prefix, ctx.org_id, agent_session_id)
        digest = await self._vms.snapshot(vm.name, to)
        log.info("session %s: VM %s kept as %s", agent_session_id, vm.name, to)
        return VmSnapshot(reference=to, digest=digest)

    async def holds(self, ctx: TenantContext, agent_session_id: UUID) -> bool:
        return await self._storage.read_of_session(ctx.org_id, agent_session_id) is not None

    async def release(self, ctx: TenantContext, agent_session_id: UUID) -> None:
        vm = await self._storage.read_of_session(ctx.org_id, agent_session_id)
        if vm is not None:
            await self._let_go(ctx, vm)

    async def recycle(self, ctx: TenantContext, agent_session_id: UUID) -> bool:
        vm = await self._storage.read_of_session(ctx.org_id, agent_session_id)
        if vm is None or not self._aged(vm, self._clock()):
            return False
        log.info("VM %s of session %s is past its maximum age, and goes", vm.name, agent_session_id)
        await self._let_go(ctx, vm)
        return True

    async def purge(self, org_id: UUID, agent_session_id: UUID) -> None:
        vm = await self._storage.read_of_session(org_id, agent_session_id)
        if vm is not None:
            await self._let_go(self._edge(), vm)
        await self.erase(org_id, agent_session_id)

    async def erase(self, org_id: UUID, agent_session_id: UUID) -> None:
        # Asked first: a process that reaches no VM, as the API's does,
        # leaves it to the sweep, which does, and one that fails part way is
        # finished there.
        asked = PoolErasure(
            id=new_id(),
            created_at=self._clock(),
            tenant_id=org_id,
            agent_session_id=agent_session_id,
        )
        standing = await self._storage.ask_erase(asked)
        if await self._reaches_vms():
            await self._erased(standing)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._expired(ctx):
            return 0
        gone = 0
        for vm in await self._storage.read_of_tenant(ctx.org_id, self._options.page):
            await self._let_go(ctx, vm)
            gone += 1
        prefix = self._options.prefix
        for name in await self._vms.names(tenant_snapshots(prefix, ctx.org_id)):
            if is_snapshot(prefix, name):
                await self._vms.destroy(name)
                gone += 1
        if await self._storage.delete_tenant_limit(ctx.org_id) is not None:
            gone += 1
        return gone

    # A VM's host.

    async def enroll(
        self, rctx: RequestContext, key: str, enrollment: Enrollment
    ) -> IssuedCredential:
        if not key.startswith(KEY_PREFIX):
            raise InvalidCredential("a VM enrolls with the key it was handed")
        digest = hash_token(key)
        vm = await self._storage.read_by_key(digest)
        if vm is None:
            raise InvalidCredential("unknown or spent VM key")
        if vm.tenant_id is None or vm.pool_id is None or vm.bound_by is None:
            raise VmUnbound(f"VM {vm.name} serves no session yet; ask again")
        if not await self._storage.spend_key(vm.id, digest):
            raise InvalidCredential("unknown or spent VM key")
        issued = await self._hosts().admit_vm(
            rctx,
            vm.tenant_id,
            vm.pool_id,
            vm.bound_by,
            vm.id,
            enrollment,
        )
        await self._storage.mark_enrolled(vm.id, issued.claimant_id)
        if vm.cold:
            # Once a cold start: its key is spent here, and a start again
            # binds it anew. A warm VM's boot was over before its claim.
            booted = (self._clock() - vm.created_at).total_seconds()
            source = "image" if vm.restored_from is None else "snapshot"
            CLOUD_POOL_BOOT_SECONDS.labels(source=source).observe(booted)
            log.info("VM %s booted from its %s in %.1fs", vm.name, source, booted)
        log.info(
            "VM %s: its host %s enrolled for session %s",
            vm.name,
            issued.claimant_id,
            vm.agent_session_id,
        )
        return issued

    # The sweep.

    async def sweep(self, rctx: RequestContext) -> int:
        # A process that reaches no VM reads every one as gone: it sweeps none.
        if not await self._reaches_vms():
            return 0
        now = self._clock()
        acted = 0
        held: set[str] = set()
        ran: list[PoolVm] = []
        after: UUID | None = None
        while True:
            page = await self._storage.read_vms(self._options.page, after)
            for vm in page:
                held.add(vm.name)
                if await self._swept(rctx, vm, now):
                    acted += 1
                elif vm.started_at is not None:
                    ran.append(vm)
            if len(page) < self._options.page:
                break
            after = page[-1].id
        prefix = self._options.prefix
        named = set(await self._vms.names(f"{prefix}{MARK}"))
        # Listed after its row was read: a VM that had run by then and is
        # listed no more died under it, or another path let it go.
        for vm in ran:
            if vm.name not in named and await self._died(rctx, vm):
                acted += 1
        for name in sorted(named):
            # A snapshot is kept under its session's names; a VM is not.
            if is_snapshot(prefix, name) or name == self._options.image or name in held:
                continue
            # Read again just before a destroy: a start writes its row before
            # its VM, so a VM whose row the pass did not read may
            # have one now.
            if await self._storage.read_by_name(name) is None:
                log.warning("VM %s is held by no row of the pool, and goes", name)
                await self._vms.destroy(name)
                acted += 1
        for erasure in await self._storage.read_erasures(self._options.page):
            await self._erased(erasure)
        await self._refill()
        return acted

    async def close(self) -> None:
        if self._starting:
            await asyncio.gather(*self._starting, return_exceptions=True)

    # The parts.

    async def _vm_for(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        pool: HostPool,
        restore: KeptSnapshot | None,
    ) -> PoolVm:
        """The VM that serves the session, running: the one it holds,
        unless a restore replaces it; else a warm one; else a new one."""
        current = await self._storage.read_of_session(ctx.org_id, agent_session_id)
        if current is not None and restore is not None and current.restored_from != restore.id:
            # A restore replaces the VM whole.
            await self._let_go(ctx, current)
            current = None
        if current is not None:
            return await self._running(ctx, agent_session_id, spec, current)
        if restore is not None:
            await self._held_to(agent_session_id, restore)
        return await self._start(ctx, agent_session_id, spec, pool, restore)

    async def _running(
        self, ctx: TenantContext, agent_session_id: UUID, spec: IsolationSpec, vm: PoolVm
    ) -> PoolVm:
        """The session's VM, running. One still on its first start waits
        on the resource, unless its start died; one that stopped starts again
        on its own disk under a new key, since its host's credential ended
        with it, and a start again that fails leaves it stopped, for the next
        ask; one gone is forgotten, and another starts."""
        if vm.started_at is None:
            if self._clock() - vm.created_at < self._options.boot:
                raise IsolationRefused(
                    f"session {agent_session_id}'s VM {vm.name} is starting", clears=True
                )
            await self._let_go(ctx, vm)
            raise IsolationRefused(
                f"session {agent_session_id}'s VM {vm.name} did not start in time; "
                "another starts at the next ask",
                clears=True,
            )
        state = await self._vms.state(vm.name)
        if state is VmState.RUNNING:
            return vm
        if state is VmState.ABSENT:
            await self._let_go(ctx, vm)
            raise IsolationRefused(
                f"session {agent_session_id}'s VM {vm.name} is gone; another starts at the "
                "next ask",
                clears=True,
            )
        await self._retire(ctx, vm)
        key = new_key()
        again = await self._storage.rekey(vm.id, hash_token(key), vm.restored_from, self._clock())
        if again is None:
            raise IsolationRefused(f"session {agent_session_id}'s VM is gone", clears=True)
        await self._seeds.launch_seeded(
            vm.name, self._spec(spec), None, seed(self._options.api_url, key)
        )
        await self._storage.mark_started(vm.id, self._clock())
        return again

    async def _start(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        pool: HostPool,
        restore: KeptSnapshot | None,
    ) -> PoolVm:
        """The session's VM: a warm one it claims, when it starts from the
        pool's image at the default size, else a new one of its size, from
        its snapshot or the pool's image, within the pool's limits as they
        stand now. Its row
        is written first, so a start that dies leaves a row the sweep finds;
        one that fails here leaves nothing. Past a maximum, the loop waits on
        the resource."""
        key = new_key()
        now = self._clock()
        vm = PoolVm(
            id=new_id(),
            created_at=now,
            name=vm_name(self._options.prefix),
            egress_open=spec.egress.mode is EgressMode.OPEN,
            tenant_id=ctx.org_id,
            agent_session_id=agent_session_id,
            pool_id=pool.id,
            bound_by=ctx.user_id,
            key_digest=hash_token(key),
            restored_from=None if restore is None else restore.id,
            bound_at=now,
        )
        limits = await self._limits()
        own = await self._storage.read_tenant_limit(ctx.org_id)
        got = await self._storage.claim(
            vm,
            most=limits.most,
            tenant_most=limits.tenant_most if own is None else own.most,
            warm=restore is None and size_of(spec) is DEFAULT_SIZE,
        )
        if isinstance(got, Full):
            # The cause is what the tenant reads: no count, and no other
            # tenant's use.
            log.info("session %s waits: the cloud pool's %s maximum stands", agent_session_id, got)
            raise IsolationRefused(
                f"session {agent_session_id} waits for a VM of the cloud pool",
                clears=True,
                cause=FULL_CAUSES[got],
            )
        if got.id != vm.id:
            log.info("session %s claimed warm VM %s", agent_session_id, got.name)
            self._spawn(self._refill())
            return got
        source = self._options.image if restore is None else restore.reference
        await self._launch(vm, self._spec(spec), source, key)
        log.info("session %s: VM %s started from %s", agent_session_id, vm.name, source)
        return vm

    async def _limits(self) -> PoolLimits:
        """The pool's limits as its operators last wrote them, else as its
        options name them."""
        return standing_limits(await self._storage.read_limits(), self._options, self._clock())

    async def _launch(self, vm: PoolVm, spec: VmSpec, source: str, key: str) -> None:
        """Starts the VM its row names, handed its key, and marks it
        started; one that fails goes with its row."""
        try:
            await self._seeds.launch_seeded(vm.name, spec, source, seed(self._options.api_url, key))
        except BaseException:
            try:
                await self._vms.destroy(vm.name)
            finally:
                await self._storage.delete_vm(vm.id)
            raise
        await self._storage.mark_started(vm.id, self._clock())

    async def _enrolled(self, agent_session_id: UUID, vm: PoolVm) -> PoolVm:
        """The VM once its host has enrolled, waited on a while."""
        by = self._clock() + self._options.ready_wait
        polls = Retries(self._poll)
        while True:
            found = await self._storage.read_vm(vm.id)
            if found is None:
                raise IsolationRefused(
                    f"session {agent_session_id}'s VM {vm.name} is gone", clears=True
                )
            if found.host_id is not None:
                return found
            left = (by - self._clock()).total_seconds()
            if left <= 0:
                raise IsolationRefused(
                    f"session {agent_session_id}'s VM {vm.name} runs, and its host has not "
                    "enrolled yet",
                    clears=True,
                )
            await self._sleep(min(polls.failed(), left))

    async def _held(
        self, ctx: TenantContext, agent_session_id: UUID, spec: IsolationSpec, pool: HostPool
    ) -> AgentWorkspace:
        """The workspace once the VM's host holds it, waited on a while:
        its host is asked to prepare it through the exec relay, as any host is."""
        by = self._clock() + self._options.ready_wait
        polls = Retries(self._poll)
        while True:
            hosts = await self._hosts().get_hosts(ctx, pool.id)
            placed = PlacementState(
                agent_session_id=agent_session_id,
                pool=pool,
                hosts_online=sum(1 for status in hosts if status.online),
            )
            try:
                held = await self._placed().held_on_host(ctx, agent_session_id, spec, pooled=placed)
            except InfraException as refused:
                waits = isinstance(refused, IsolationRefused) and refused.clears
                if not waits or self._clock() >= by:
                    raise
            else:
                assert held is not None  # a pool of one is given
                return held
            left = (by - self._clock()).total_seconds()
            await self._sleep(max(0.0, min(polls.failed(), left)))

    async def _held_to(self, agent_session_id: UUID, restore: KeptSnapshot) -> None:
        """The snapshot's disk, held to the digest the pool recorded, before
        anything starts from it: one gone or altered loses the workspace."""
        digest = await self._vms.digest(restore.reference)
        if digest is None:
            raise AgentWorkspaceLost(
                f"snapshot {restore.id} of session {agent_session_id} is gone from the VMs' store"
            )
        if digest != restore.digest:
            raise AgentWorkspaceLost(
                f"snapshot {restore.id} of session {agent_session_id} does not match its digest"
            )

    async def _let_go(self, rctx: RequestContext, vm: PoolVm) -> None:
        """The VM goes: its host's credential ends, then the VM and
        its disk, then its row."""
        await self._retire(rctx, vm)
        await self._vms.destroy(vm.name)
        await self._storage.delete_vm(vm.id)
        log.info("VM %s of session %s let go", vm.name, vm.agent_session_id)

    async def _retire(self, rctx: RequestContext, vm: PoolVm) -> None:
        if vm.host_id is not None and vm.tenant_id is not None:
            by = vm.bound_by or vm.host_id
            await self._hosts().retire_host(rctx, vm.tenant_id, vm.host_id, by)

    async def _swept(self, rctx: RequestContext, vm: PoolVm, now: datetime) -> bool:
        """Whether the sweep acted on a VM. It lets go of a start older
        than the boot bound that never ran, whose disk is its source's, and
        of a VM whose session, or tenant, is gone. It stops a session's
        VM that runs with no host to work for, and keeps its disk: the
        session's next prepare starts it again under a new key, and the
        session's end lets it go."""
        if vm.started_at is None:
            if now - vm.created_at <= self._options.boot:
                return False
            if vm.warm:
                return await self._drop_warm(vm)
            await self._let_go(rctx, vm)
            return True
        if vm.tenant_id is None or vm.agent_session_id is None:
            # Warm: no host enrolls until a session claims it, and no loop
            # runs on it, so one past its age goes, and the refill starts
            # another.
            return vm.warm and self._aged(vm, now) and await self._drop_warm(vm)
        if await self._session_gone(vm.tenant_id, vm.agent_session_id):
            await self._let_go(rctx, vm)
            return True
        if not await self._hostless(rctx, vm, now):
            return False
        if await self._vms.state(vm.name) is not VmState.RUNNING:
            return False
        log.warning(
            "VM %s of session %s runs with no host to work for, and stops",
            vm.name,
            vm.agent_session_id,
        )
        await self._retire(rctx, vm)
        await self._vms.stop(vm.name)
        return True

    async def _died(self, rctx: RequestContext, vm: PoolVm) -> bool:
        """Whether a VM that ran, and is listed no more, is gone, and was
        let go: its host's credential ends and its row goes, so it holds no
        place under a maximum, and its session's next prepare starts
        another."""
        if await self._vms.state(vm.name) is not VmState.ABSENT:
            return False
        log.warning("VM %s of session %s is gone, and is let go", vm.name, vm.agent_session_id)
        if vm.warm:
            return await self._drop_warm(vm)
        await self._let_go(rctx, vm)
        return True

    async def _drop_warm(self, vm: PoolVm) -> bool:
        """A warm VM goes: its row first, under the lock its claims take,
        then the VM. A session that claimed it meanwhile keeps it."""
        if not await self._storage.take_warm(vm.id):
            return False
        await self._vms.destroy(vm.name)
        log.info("warm VM %s let go", vm.name)
        return True

    def _aged(self, vm: PoolVm, now: datetime) -> bool:
        """Whether a VM is past the pool's maximum age, from its row's start."""
        return now - vm.created_at > self._options.max_age

    async def _hostless(self, rctx: RequestContext, vm: PoolVm, now: datetime) -> bool:
        """Whether a session's VM has no host to work for: none enrolled
        within the boot bound and the wait after the VM was handed its
        key for the session, or its host was ended, or has not called within
        the silence bound."""
        if vm.host_id is None:
            since = vm.bound_at or vm.created_at
            return now - since > self._options.boot + self._options.ready_wait
        assert vm.tenant_id is not None  # a session's VM names its tenant
        host = await self._hosts().vm_host(rctx, vm.tenant_id, vm.host_id)
        if host is None or host.revoked_at is not None:
            return True
        return now - host.last_seen_at > self._options.silent

    async def _reaches_vms(self) -> bool:
        """Whether this process reaches the pool's VMs, as the runner's
        and the sweep's do."""
        if not self._options.image:
            return False
        return await self._vms.probe(longest_name(self._options.prefix)) is None

    async def _erased(self, erasure: PoolErasure) -> None:
        """Every disk kept under the session's names goes, then the ask."""
        named = snapshots_of(self._options.prefix, erasure.tenant_id, erasure.agent_session_id)
        for name in await self._vms.names(named):
            await self._vms.destroy(name)
        await self._storage.delete_erasure(erasure.id)

    async def _refill(self) -> None:
        """Starts warm VMs, in the background, until the warm count
        stands, never past the most the pool holds, as its limits stand
        now."""
        if not self._options.image:
            return
        limits = await self._limits()
        if not limits.warm:
            return
        keys = [new_key() for _ in range(limits.warm)]
        egress_open = not self._vms.closes_egress()
        made = [
            PoolVm(
                id=new_id(),
                created_at=self._clock(),
                name=vm_name(self._options.prefix),
                egress_open=egress_open,
                key_digest=hash_token(key),
            )
            for key in keys
        ]
        written = await self._storage.reserve_warm(limits.warm, limits.most, made)
        if not written:
            return
        spec = self._sized(DEFAULT_SIZE, egress_open=egress_open)
        for vm, key in zip(made[:written], keys[:written], strict=True):
            self._spawn(self._warm(vm, spec, key))
        log.info("the cloud pool starts %d warm VMs", written)

    async def _warm(self, vm: PoolVm, spec: VmSpec, key: str) -> None:
        try:
            await self._launch(vm, spec, self._options.image, key)
        except Exception:
            log.exception("warm VM %s did not start, and is let go", vm.name)

    def _edge(self) -> RequestContext:
        """The request stage a purge runs under, which runs for no request:
        minted by the process's edge."""
        if self._stage is None:
            raise RuntimeError("this process mints no request stage for the cloud pool's purge")
        return self._stage()

    def _spawn(self, work: Awaitable[None]) -> None:
        task = asyncio.ensure_future(work)
        self._starting.add(task)
        task.add_done_callback(self._starting.discard)

    def _spec(self, spec: IsolationSpec) -> VmSpec:
        return self._sized(size_of(spec), egress_open=spec.egress.mode is EgressMode.OPEN)

    def _sized(self, size: VmSize, *, egress_open: bool) -> VmSpec:
        """A VM of `size`, as the deployment's map names it: its machine
        type for a cloud that starts types, its cpus and its memory for one
        that holds them."""
        machine = self._options.sizes.of(size)
        assert machine is not None  # a size not allowed is refused before
        return VmSpec(
            image=self._options.vm_image,
            cpus=machine.cpus,
            memory_mb=machine.memory_mb,
            machine_type=machine.name,
            egress_open=egress_open,
        )
