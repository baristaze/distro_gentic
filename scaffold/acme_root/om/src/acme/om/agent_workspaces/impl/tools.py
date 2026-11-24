"""The tools manager as the platform runs it: the engine's, with every
workspace held to its session's pin. A prepare asks for the pinned isolation
whatever a loop asks, and the host refuses what it cannot give
(`rules.host_refusal`) before its provider is reached, so the loop parks on
the resource and no weaker place is made. Each refusal, the host's or its
provider's, clears: a host of the session's placement may give it later, so
the loop asks again and never ends for one. A prepared workspace is brought
up to the session's branch; a release first pushes what the workspace
holds, then lets go only of what its own run holds. A restore, a rewind or a
fork's, starts a workspace this process prepares from the platform's
bucket, and one a host of the tenant's holds from that host's store, never
across the wall. A fork of a workspace a host holds is taken by that host
at the spawn and kept there as the child's (`fork_point`). The pin holds the
session's durability and base with its isolation. A provider's refusal
clears, since another host may give the isolation later, unless it refuses
what the prepare asks beyond it (a snapshot's durability, a base, or a
restore): that refusal is for good, and ends the loop with its reason.
What a prepare would refuse for good, here or on the cloud pool, is asked
of the pin before the loop's first model call (`check_pinned`). A
workspace a snapshot started keeps the tree the snapshot holds: its branch
is not brought up over it. Every other operation is the engine's,
unchanged.

A run is named by its epoch, read from storage as it prepares: a session
that resumes on this host while the run before it is still being released
is the later run's from the moment its prepare starts here, so the earlier
release leaves its instance, and what this host holds of it, to the later
one. A later run on another host makes its own there, and this host's goes.

The host is this process: what it offers and how many directory sessions it
holds live are its own, never the control plane's. A session that runs
inside its tenant's wall is the exception: its workspace is the one the host
of its pool holds (`PlacedWorkspacesInterface`), which this process neither
makes nor lets go, and its checkout runs there through the relay. So is a
session of the cloud whose workspace is a VM, when the cloud pool runs
VMs here (`CloudPoolManagerInterface`): its workspace is the one the
host of its own VM holds, through the relay as well. Its snapshot keeps
the workspace's directory alone, as a VM workspace's does: once what the
workspace holds is pushed, the directory is packed and compressed in the
VM, read out through the relay in parts, each sealed under a key of its
own, which the archive keeps under the session's key, and kept in the
platform's bucket, and the VM goes when the run's release comes, no disk
of it kept. A restore starts a VM from the pool's image, whose host
fetches the parts from the bucket itself, several at once, and brings the
directory back into it, so what its commands installed outside it comes
from the image again (`pool_directory`, `pool_archive`, ADR 2070, ADR
2077)."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import Field

from acme.infra.agent_workspaces import (
    AgentWorkspace,
    AgentWorkspaceLost,
    Durability,
    EgressMode,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    SnapshotRefused,
)
from acme.infra.buckets import BucketsInterface
from acme.infra.exceptions import InfraException
from acme.infra.observability import CLOUD_POOL_RESTORE_SECONDS
from acme.infra.transports import OutputSink, TransportInterface
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agent_steps.types.header import HASH_SCHEME, AgentWorkspaceSnapshot, SnapshotHolds
from acme.om.agent_workspaces.impl import pool_archive, pool_directory
from acme.om.agent_workspaces.manager import AgentWorkspacesManagerInterface
from acme.om.agent_workspaces.pinned import PinnedWorkspacesInterface
from acme.om.agent_workspaces.placed import PlacedWorkspacesInterface
from acme.om.agent_workspaces.rules import host_refusal
from acme.om.agent_workspaces.types.host import HostOffer
from acme.om.agent_workspaces.types.snapshot import HostSnapshot, KeptSnapshot
from acme.om.base import OmBase, new_id, utcnow
from acme.om.cloud_pool import CloudPoolManagerInterface
from acme.om.cloud_pool.rules import archive_size
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import NotFound
from acme.om.exec_relay.exceptions import FetchNotRead
from acme.om.tools.impl.snapshots import Manifest, SnapshotStore, snapshot_key
from acme.om.tools.manager import KeyedHash, ToolsManagerInterface
from acme.om.tools.registry import ToolRegistry
from acme.om.tools.rules import injected_secrets, named_snapshot, snapshotted_step
from acme.om.tools.seal import RecordSealInterface
from acme.om.tools.tool import TakenSnapshot, TakeSnapshot, ToolInterface
from acme.om.tools.types.call import Gate, JobHandle, JobNotStarted
from acme.om.tools.types.policy import ToolPolicy, ToolPolicyLayer
from acme.timing import Retries, RetryPolicy

log = logging.getLogger(__name__)


class PinnedToolsOptions(OmBase):
    # How long a run's end waits for the host that holds its workspace to
    # keep a snapshot of it.
    snapshot_wait: timedelta = Field(default=timedelta(minutes=10), gt=timedelta(0))
    # How long a VM of the cloud pool may take to pack its workspace's
    # directory, or to unpack one into it once its parts are written.
    pack_within: timedelta = Field(default=timedelta(minutes=10), gt=timedelta(0))


EraseOnHost = Callable[[TenantContext, UUID, UUID], Awaitable[None]]
"""Asks the host given, by its id, to let the session's snapshots go from its
store."""

ErasePurged = Callable[[UUID, UUID, UUID], Awaitable[None]]
"""Asks the same for a session's purge, which runs for no principal: given
the tenant, the session, and the host."""


@dataclass(frozen=True, kw_only=True)
class TakenOnHost(TakenSnapshot):
    """A live workspace a host took whole for a fork and keeps in its own
    store as the child's (`kept_for`). No byte of it reaches this process,
    so `archive` is empty: `taken` is the record of the host's answer, its
    place and its digest, under the parent whose workspace it took."""

    kept_for: UUID
    taken: KeptSnapshot


POLL = RetryPolicy(base=0.05, cap=1.0)
"""How often a host's snapshot is looked for: a wait that doubles from
50 ms to 1 s."""


def _beyond_isolation(spec: IsolationSpec, restore: AgentWorkspaceSnapshot | None) -> bool:
    """Whether a prepare asks more of its provider than the isolation: to keep
    the workspace by snapshots, to start it from a base, or to start it
    from a snapshot. A provider that refuses any of it for good refuses it
    on every host like it, so the refusal ends the loop with its reason,
    never a wait that no host ends."""
    return spec.durability is Durability.SNAPSHOT or spec.base is not None or restore is not None


class HeldWorkspaces:
    """The workspaces this host holds prepared, by session, each under the
    epoch of the run that prepared it: from a prepare that succeeded to the
    release that let it go. What a session delivered is read from the one it
    holds (`WorkProductAgentWorkspacesImpl`)."""

    def __init__(self) -> None:
        self._held: dict[UUID, tuple[AgentWorkspace, int]] = {}

    def get(self, agent_session_id: UUID) -> AgentWorkspace | None:
        held = self._held.get(agent_session_id)
        return None if held is None else held[0]

    def epoch_of(self, agent_session_id: UUID) -> int | None:
        """The epoch of the run that holds the session's workspace here."""
        held = self._held.get(agent_session_id)
        return None if held is None else held[1]

    def hold(self, workspace: AgentWorkspace, epoch: int) -> None:
        self._held[workspace.id] = (workspace, epoch)

    def let_go(self, agent_session_id: UUID, epoch: int | None = None) -> None:
        """Lets the session's workspace go: with an epoch, only when the run
        of that epoch still holds it, so a later run's stays."""
        if epoch is None or self.epoch_of(agent_session_id) == epoch:
            self._held.pop(agent_session_id, None)


class ToolsManagerAgentWorkspacesImpl(ToolsManagerInterface, PinnedWorkspacesInterface):
    def __init__(
        self,
        inner: ToolsManagerInterface,
        agent_workspaces: AgentWorkspacesManagerInterface,
        steps: AgentStepsManagerInterface,
        offer: HostOffer,
        *,
        local: bool,
        held: HeldWorkspaces | None = None,
        placed: PlacedWorkspacesInterface | None = None,
        snapshots: SnapshotStore | None = None,
        buckets: BucketsInterface | None = None,
        keyed_hash: KeyedHash | None = None,
        erase_on_host: EraseOnHost | None = None,
        erase_purged: ErasePurged | None = None,
        cloud: CloudPoolManagerInterface | None = None,
        transport: TransportInterface | None = None,
        record_seal: RecordSealInterface | None = None,
        options: PinnedToolsOptions | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._inner = inner
        self._snapshots = snapshots
        self._buckets = buckets
        self._keyed_hash = keyed_hash
        self._erase_on_host = erase_on_host
        self._erase_purged = erase_purged
        self._cloud = cloud
        self._transport = transport
        self._record_seal = record_seal
        self._snapshot_wait = (options or PinnedToolsOptions()).snapshot_wait
        self._pack_within = (options or PinnedToolsOptions()).pack_within
        self._sleep = sleep
        self._clock = clock
        self._agent_workspaces = agent_workspaces
        self._steps = steps
        self._offer = offer
        self._local = local
        self._held = held or HeldWorkspaces()
        self._placed = placed
        # The directory workspaces live here, each under its run's epoch.
        self._directories: dict[UUID, int] = {}
        self._hosted: set[UUID] = set()  # the workspaces a host of the tenant's holds
        self._pooled: set[UUID] = set()  # the workspaces a VM of the cloud pool holds
        self._archived: set[UUID] = set()  # pooled ones whose directory the run's end kept
        self._preparing: dict[UUID, int] = {}  # the prepares under way here, by session

    # The workspace.

    async def check_agent_workspace(self, ctx: TenantContext, spec: IsolationSpec) -> None:
        if spec.mode is IsolationMode.NONE:
            await self._inner.check_agent_workspace(ctx, spec)
            return
        ctx.require(Permission.WRITE)
        # The kind's spec, which names no session: one the cloud pool runs
        # is held to what its VMs can ever hold, read of the spec alone as
        # the transport reads it, and one they never can is refused before
        # the loop's first model call, and no VM starts. The session's pin,
        # held where it is placed, is the platform's loop hooks' to check
        # (`check_pinned`).
        if self._cloud is not None and await self._cloud.runs(spec):
            await self._cloud.check(spec)

    async def check_pinned(
        self, ctx: TenantContext, agent_session_id: UUID, asked: IsolationSpec
    ) -> None:
        ctx.require(Permission.WRITE)
        try:
            pinned = (await self._agent_workspaces.get_workspace(ctx, agent_session_id)).spec()
        except NotFound:
            # Pinned at its first prepare, to what its loop asks.
            pinned = asked
        if pinned.mode is IsolationMode.NONE:
            return
        # Placed as its prepare places it.
        try:
            pool = (
                None if self._placed is None else await self._placed.pool_of(ctx, agent_session_id)
            )
        except NotFound:
            return  # its pool is gone: it waits for it, as its prepare does
        if pool is not None:
            return
        if self._cloud is not None and await self._cloud.runs(pinned):
            await self._cloud.check(pinned)
            return
        if not _beyond_isolation(pinned, None):
            # A refusal of the isolation alone clears: another host may give it.
            return
        try:
            await self._inner.check_agent_workspace(ctx, pinned)
        except InfraException as refused:
            if not (isinstance(refused, IsolationRefused) and refused.clears):
                raise

    async def prepare_agent_workspace(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        restore: AgentWorkspaceSnapshot | None = None,
    ) -> AgentWorkspace:
        # Marked before the first await, and until the workspace is held: a
        # release that lands meanwhile leaves the instance to this run.
        self._preparing[agent_session_id] = self._preparing.get(agent_session_id, 0) + 1
        try:
            return await self._prepare(ctx, agent_session_id, spec, restore)
        finally:
            left = self._preparing.pop(agent_session_id) - 1
            if left:
                self._preparing[agent_session_id] = left

    async def _prepare(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        restore: AgentWorkspaceSnapshot | None,
    ) -> AgentWorkspace:
        pinned = await self._agent_workspaces.pinned(ctx, agent_session_id, spec)
        if pinned.mode is IsolationMode.NONE:
            return await self._inner.prepare_agent_workspace(ctx, agent_session_id, pinned, restore)
        # The run that prepares it took its epoch just before: what this
        # host holds for the session is held under it.
        epoch = (await self._steps.get_cursor(ctx, agent_session_id)).epoch
        pool = None if self._placed is None else await self._placed.pool_of(ctx, agent_session_id)
        if pool is None and self._cloud is not None and await self._cloud.runs(pinned):
            return await self._on_vm(ctx, agent_session_id, pinned, restore, epoch)
        if self._placed is not None and pool is not None:
            # A restore is decided before any host is asked, and travels
            # with the ask: its host starts the workspace from it.
            kept = (
                None
                if restore is None
                else await self._in_store(ctx, agent_session_id, pool, restore)
            )
            hosted = await self._placed.held_on_host(ctx, agent_session_id, pinned, kept)
            if hosted is not None:
                # Its host made it to the pin and holds it; the checkout is
                # brought up to the session's branch there, unless a
                # snapshot started it.
                attached = await self._agent_workspaces.attach(
                    ctx, hosted, epoch, restored=restore is not None
                )
                self._hosted.add(agent_session_id)
                self._held.hold(attached, epoch)
                return attached
        if restore is not None:
            await self._in_bucket(ctx, agent_session_id, restore)
        running = len(self._directories.keys() - {agent_session_id})
        why = host_refusal(pinned, self._offer, local=self._local, running=running)
        if why is not None:
            raise IsolationRefused(why, clears=True)
        # Held before the first await, so two prepares at once count each
        # other.
        if pinned.mode is IsolationMode.HOST:
            self._directories[agent_session_id] = epoch
        try:
            workspace = await self._inner.prepare_agent_workspace(
                ctx, agent_session_id, pinned, restore
            )
        except InfraException as refused:
            self._directories.pop(agent_session_id, None)
            if (
                isinstance(refused, IsolationRefused)
                and not refused.clears
                and not _beyond_isolation(pinned, restore)
            ):
                # Another host of the session's placement may give the
                # isolation later.
                raise IsolationRefused(refused.message, clears=True) from refused
            raise
        except BaseException:
            self._directories.pop(agent_session_id, None)
            raise
        try:
            attached = await self._agent_workspaces.attach(
                ctx, workspace, epoch, restored=restore is not None
            )
        except BaseException:
            # Its instance goes, and its files stay as they were: nothing of
            # the loop ran in it.
            try:
                await self._inner.release_agent_workspace(ctx, workspace)
            except Exception:
                log.exception("session %s: the workspace was not released", agent_session_id)
            self._directories.pop(agent_session_id, None)
            raise
        self._held.hold(attached, epoch)
        return attached

    async def release_agent_workspace(self, ctx: TenantContext, workspace: AgentWorkspace) -> None:
        # The run that releases it holds it until here: a later run's
        # prepare cannot land before its first await.
        epoch = self._held.epoch_of(workspace.id)
        # A VM whose directory the run's end kept had its work pushed just
        # before, and nothing ran in it since.
        archived = workspace.id in self._archived
        if workspace.spec.mode is not IsolationMode.NONE and not archived:
            # Kept first: a push that does not land raises, and the instance
            # and its work stay. Its commands carry the epoch of the run that
            # holds it, or, for one this process never held, the epoch read
            # now: a run that claims the session after that is not reached.
            fence = epoch
            if fence is None:
                fence = (await self._steps.get_cursor(ctx, workspace.id)).epoch
            await self._agent_workspaces.detach(ctx, workspace, fence)
        if epoch is not None and self._taken_here(workspace.id, epoch):
            # The session resumed here while its work was kept: the instance
            # is the later run's, to let go when it ends.
            log.info("session %s: a later run holds its workspace, which stays", workspace.id)
        elif archived:
            # Its directory is the snapshot the run's end kept: the VM
            # goes, no disk of it kept, and the next loop's VM takes the
            # directory back.
            assert self._cloud is not None
            self._archived.discard(workspace.id)
            self._pooled.discard(workspace.id)
            await self._cloud.release(ctx, workspace.id)
        elif workspace.id in self._hosted or workspace.id in self._pooled:
            # Its host holds it, warm for the next loop: nothing of this
            # process's goes. A VM of the cloud pool is let go past the
            # grace, by the sweep, or now when it is past its age, since
            # its work was just kept; one kept by snapshots is not, since
            # its disk holds what no snapshot kept.
            pooled = workspace.id in self._pooled
            self._hosted.discard(workspace.id)
            self._pooled.discard(workspace.id)
            if pooled and workspace.spec.durability is Durability.CACHE:
                await self._recycled(ctx, workspace.id)
        else:
            await self._inner.release_agent_workspace(ctx, workspace)
        if epoch is not None:
            # Only what this run holds: a later run's stays held.
            self._held.let_go(workspace.id, epoch)
            if self._directories.get(workspace.id) == epoch:
                del self._directories[workspace.id]

    async def snapshot_agent_workspace(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        workspace: AgentWorkspace,
        *,
        epoch: int,
        loop_id: UUID,
        tools: Sequence[ToolInterface],
    ) -> AgentStep:
        if agent_session_id in self._hosted:
            # Its host holds it: the host takes the snapshot, and its bytes
            # stay in the host's store, inside the wall.
            return await self._snapshot_on_host(
                ctx, agent_session_id, workspace, epoch=epoch, loop_id=loop_id
            )
        if agent_session_id in self._pooled:
            # Its VM's directory, read out through the relay and kept in
            # the platform's bucket under the session's key.
            return await self._snapshot_on_vm(
                ctx, agent_session_id, workspace, epoch=epoch, loop_id=loop_id, tools=tools
            )
        step = await self._inner.snapshot_agent_workspace(
            ctx, agent_session_id, workspace, epoch=epoch, loop_id=loop_id, tools=tools
        )
        taken = named_snapshot(step)
        if taken is not None:
            await self._recorded(ctx, agent_session_id, taken)
        return step

    def fork_point(
        self, ctx: TenantContext, request: AgentStep, workspace: AgentWorkspace, epoch: int
    ) -> TakeSnapshot | None:
        """The fork point of a workspace a host of the tenant's holds, for the
        engine's tools (`ForkPoints`): that host takes it, before the tree's
        slot is taken or the child is made. None for every other workspace,
        which the engine takes through its own provider, or refuses."""
        if workspace.id in self._hosted:
            return lambda: self._fork_on_host(ctx, request, workspace)
        return None

    async def fork_snapshot(
        self, ctx: TenantContext, child_id: UUID, snapshot_id: UUID, taken: TakenSnapshot
    ) -> AgentWorkspaceSnapshot:
        if isinstance(taken, TakenOnHost):
            return await self._copy_on_host(ctx, child_id, snapshot_id, taken)
        kept = await self._inner.fork_snapshot(ctx, child_id, snapshot_id, taken)
        await self._recorded(ctx, child_id, kept)
        return kept

    async def find_snapshot(
        self, ctx: TenantContext, agent_session_id: UUID, snapshot_id: UUID
    ) -> AgentWorkspaceSnapshot:
        return await self._inner.find_snapshot(ctx, agent_session_id, snapshot_id)

    def _taken_here(self, agent_session_id: UUID, epoch: int) -> bool:
        """Whether a later run in this process prepares the session's
        workspace or holds it. One on another host, or one that never
        prepares, takes nothing of this host's."""
        held = self._held.epoch_of(agent_session_id)
        return agent_session_id in self._preparing or (held is not None and held != epoch)

    async def purge_agent_workspace(self, org_id: UUID, agent_session_id: UUID) -> None:
        # The engine's purge takes the files, the instance, and every
        # snapshot in the platform's bucket. Each host whose store keeps one
        # is asked to let them go while the records still name it; the
        # records go last.
        await self._inner.purge_agent_workspace(org_id, agent_session_id)
        hosts = await self._agent_workspaces.snapshot_hosts(org_id, agent_session_id)
        if hosts and self._erase_purged is None:
            log.error("session %s: no host is asked to erase its snapshots", agent_session_id)
        elif self._erase_purged is not None:
            for host_id in sorted(hosts):
                await self._erase_purged(org_id, agent_session_id, host_id)
        if self._cloud is not None:
            # Its VM, and the pool's record of its archives.
            await self._cloud.purge(org_id, agent_session_id)
        await self._agent_workspaces.forget_snapshots(org_id, agent_session_id)
        await self._agent_workspaces.purge_agent_session(org_id, agent_session_id)
        self._held.let_go(agent_session_id)
        self._directories.pop(agent_session_id, None)
        self._hosted.discard(agent_session_id)
        self._pooled.discard(agent_session_id)
        self._archived.discard(agent_session_id)

    async def erase_snapshots(self, ctx: TenantContext, agent_session_id: UUID) -> None:
        # The session's key is gone, so its archives are noise: they leave
        # the bucket, and what its provider keeps outside them goes with
        # them. A copy kept for another session, a fork's, is that one's.
        # A host's store keeps its bytes unsealed inside the wall: each host
        # that keeps one is asked to let them go.
        await self._inner.erase_snapshots(ctx, agent_session_id)
        if self._snapshots is not None:
            await self._snapshots.purge(ctx.org_id, agent_session_id)
        if self._cloud is not None:
            # The pool's record of the session's archives, now noise.
            await self._cloud.erase(ctx.org_id, agent_session_id)
        kept = await self._agent_workspaces.kept_snapshots(ctx, agent_session_id)
        hosts = {record.host_id for record in kept if record.host_id is not None}
        if hosts and self._erase_on_host is None:
            log.error("session %s: no host is asked to erase its snapshots", agent_session_id)
        elif self._erase_on_host is not None:
            for host_id in sorted(hosts):
                await self._erase_on_host(ctx, agent_session_id, host_id)
        await self._agent_workspaces.forget_snapshots(ctx.org_id, agent_session_id)

    async def keep_on_host(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        snapshot: HostSnapshot,
        pool_id: UUID,
        host_id: UUID,
    ) -> None:
        """Records a snapshot a host kept in its own store, by the reference
        and the digest it answered, never its bytes. The hash the history
        names is the digest's, keyed by the session, so once its key is
        revoked nothing confirms what it held."""
        assert snapshot.reference is not None and snapshot.digest is not None
        assert snapshot.size is not None  # a kept snapshot's answer names all three
        if self._keyed_hash is None:
            raise SnapshotRefused("this process keys no hash, so it records no host's snapshot")
        keyed = await self._keyed_hash(ctx, agent_session_id, snapshot.digest.encode())
        now = self._clock()
        await self._agent_workspaces.keep_snapshot(
            ctx,
            KeptSnapshot(
                id=snapshot.id,
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                agent_session_id=agent_session_id,
                hash=HASH_SCHEME + keyed,
                size=snapshot.size,
                pool_id=pool_id,
                host_id=host_id,
                reference=snapshot.reference,
                digest=snapshot.digest,
            ),
        )

    async def _snapshot_on_host(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        workspace: AgentWorkspace,
        *,
        epoch: int,
        loop_id: UUID,
    ) -> AgentStep:
        """The snapshot the host that holds the workspace keeps in its own
        store, once it is recorded, and the step that names it. The host
        takes back what its broker attached, scans for its secrets' values,
        and keeps nothing that holds one."""
        snapshot_id = new_id()
        record = await self._kept_on_host(ctx, agent_session_id, workspace.spec, snapshot_id)
        taken = AgentWorkspaceSnapshot(
            id=snapshot_id, hash=record.hash, size=record.size, agent_workspace_id=workspace.id
        )
        step = snapshotted_step(new_id(), self._clock(), agent_session_id, loop_id, taken)
        (stored,) = await self._steps.append_agent_steps(ctx, agent_session_id, epoch, [step])
        return stored

    async def _kept_on_host(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        snapshot_id: UUID,
        *,
        kept_for: UUID | None = None,
    ) -> KeptSnapshot:
        """The record of the snapshot the host that holds the session's
        workspace keeps under `snapshot_id`, once the relay recorded its
        answer under the session: its own, or, with `kept_for`, a fork's
        copy the host keeps as that child's. `SnapshotRefused` with the
        host's reason, or when no answer comes in time."""
        assert self._placed is not None
        item_id = await self._placed.snapshot_on_host(
            ctx, agent_session_id, spec, snapshot_id, kept_for=kept_for
        )
        by = self._clock() + self._snapshot_wait
        polls = Retries(POLL)
        while (record := await self._agent_workspaces.kept_snapshot(ctx, snapshot_id)) is None:
            refused = await self._placed.refusal_of(ctx, item_id)
            if refused is not None:
                raise SnapshotRefused(f"the host kept no snapshot of the workspace: {refused}")
            left = (by - self._clock()).total_seconds()
            if left <= 0:
                raise SnapshotRefused(
                    f"the host that holds session {agent_session_id}'s workspace kept no snapshot in time"
                )
            await self._sleep(min(polls.failed(), left))
        return record

    async def _fork_on_host(
        self, ctx: TenantContext, request: AgentStep, workspace: AgentWorkspace
    ) -> TakenOnHost:
        """The workspace a host holds, taken live by that host for a spawn in
        the call `request`, and kept in its own store as the child's: a
        spawn's child takes the call's key as its id (`spawn_sub_agent`), so
        the copy is the child's before the child is made, and no erase of
        the parent's snapshots reaches it. The parent keeps nothing of it.
        Refused, with the host's reason, before anything of the tree is
        spent: a session that keeps no content at rest, no live host that
        holds the workspace, or a host that takes no snapshot of it."""
        agent_session_id = request.agent_session_id
        if self._snapshots is None:
            raise SnapshotRefused("this process keeps no snapshot store, so it forks no workspace")
        await self._snapshots.at_rest(ctx, agent_session_id)
        taken = await self._kept_on_host(
            ctx, agent_session_id, workspace.spec, new_id(), kept_for=request.id
        )
        return TakenOnHost(
            agent_workspace_id=workspace.id, archive=b"", kept_for=request.id, taken=taken
        )

    async def _copy_on_host(
        self, ctx: TenantContext, child_id: UUID, snapshot_id: UUID, taken: TakenOnHost
    ) -> AgentWorkspaceSnapshot:
        """The fork's copy a host keeps as the child's, recorded as the
        child's under `snapshot_id`: where the take lives, and its digest
        keyed by the child, so once the child's key is revoked nothing
        confirms what it held. No byte moves: the child's first prepare
        restores it on a host of the pool whose store keeps it. A child that
        keeps no content at rest keeps none, and the host is asked to let
        the copy go."""
        kept = taken.taken
        if taken.kept_for != child_id or kept.host_id is None or kept.digest is None:
            raise SnapshotRefused(
                f"the host kept the fork's copy for session {taken.kept_for}, not session {child_id}"
            )
        if self._snapshots is None or self._keyed_hash is None:
            raise SnapshotRefused("this process keys no hash, so it records no host's snapshot")
        try:
            await self._snapshots.at_rest(ctx, child_id)
        except InfraException as refused:
            if refused.code != SnapshotRefused.code:
                raise
            # Nothing names the copy, so nothing would ever erase it.
            if self._erase_on_host is None:
                log.error("session %s: no host is asked to erase its copy", child_id)
            else:
                await self._erase_on_host(ctx, child_id, kept.host_id)
            raise
        keyed = await self._keyed_hash(ctx, child_id, kept.digest.encode())
        now = self._clock()
        stored = await self._agent_workspaces.keep_snapshot(
            ctx,
            KeptSnapshot(
                id=snapshot_id,
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                agent_session_id=child_id,
                hash=HASH_SCHEME + keyed,
                size=kept.size,
                pool_id=kept.pool_id,
                host_id=kept.host_id,
                reference=kept.reference,
                digest=kept.digest,
            ),
        )
        # A spawn asked again finds the copy recorded already: the one
        # stored is the one named.
        return AgentWorkspaceSnapshot(
            id=stored.id,
            hash=stored.hash,
            size=stored.size,
            agent_workspace_id=taken.agent_workspace_id,
        )

    async def _on_vm(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        pinned: IsolationSpec,
        restore: AgentWorkspaceSnapshot | None,
        epoch: int,
    ) -> AgentWorkspace:
        """The session's workspace on its VM of the cloud pool, which
        the pool starts from its image and the VM's host holds; with
        `restore`, its directory is the snapshot's. The checkout is brought
        up to the session's branch there, unless a snapshot started it."""
        assert self._cloud is not None
        if restore is None:
            held = await self._cloud.prepare(ctx, agent_session_id, pinned)
        else:
            held = await self._restored_on_vm(ctx, agent_session_id, pinned, restore, epoch)
        attached = await self._agent_workspaces.attach(
            ctx, held, epoch, restored=restore is not None
        )
        self._pooled.add(agent_session_id)
        self._archived.discard(agent_session_id)
        self._held.hold(attached, epoch)
        return attached

    async def _restored_on_vm(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        pinned: IsolationSpec,
        restore: AgentWorkspaceSnapshot,
        epoch: int,
    ) -> AgentWorkspace:
        """A VM of the pool whose directory holds what the snapshot
        `restore` holds. The snapshot is one the platform's bucket keeps of a
        directory, and its manifest is trusted by its hash before any VM is
        asked for; a VM that serves the session for another snapshot goes,
        since a restore replaces it whole. The directory of the VM the pool
        gives is emptied and filled from the parts, each trusted only once
        it opens under its key and matches its size and its digest. One that
        fails part way lets that VM go, so no half-restored directory is
        ever found again, and touches nothing kept. One that ends is timed,
        from its first part to its unpack's end, under its archive's size
        class."""
        assert self._cloud is not None
        snapshots, _, _, _ = self._archives()
        await self._in_bucket(ctx, agent_session_id, restore)
        if restore.holds is not SnapshotHolds.DIRECTORY:
            raise AgentWorkspaceLost(
                f"snapshot {restore.id} of session {agent_session_id} holds a whole workspace, "
                "which no VM of the cloud pool starts from"
            )
        archive = await pool_archive.opened(snapshots, ctx, agent_session_id, restore)
        held = await self._cloud.prepare(ctx, agent_session_id, pinned, restore.id)
        began = self._clock()
        try:
            await self._brought_back(ctx, agent_session_id, held, archive, epoch)
        except BaseException:
            try:
                await self._cloud.release(ctx, agent_session_id)
            except Exception:
                log.exception("session %s: the VM of a lost restore stays", agent_session_id)
            raise
        took = (self._clock() - began).total_seconds()
        CLOUD_POOL_RESTORE_SECONDS.labels(size=archive_size(restore.size)).observe(took)
        return held

    async def _brought_back(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        held: AgentWorkspace,
        archive: pool_archive.PoolManifest | Manifest,
        epoch: int,
    ) -> None:
        """The archive's parts brought into the VM's directory, then
        unpacked there. The VM's host fetches the parts of an archive the
        pool keeps from the bucket itself, each by a link signed for it
        alone; for a host that fetches none, each part is opened here and
        relayed, as each of an archive kept before is, under the session's
        key."""
        snapshots, buckets, transport, record_seal = self._archives()
        if isinstance(archive, pool_archive.PoolManifest):
            packing, count = archive.packing, len(archive.parts)
            try:
                await pool_directory.fetch(
                    transport, held, archive.objects(agent_session_id), epoch=epoch
                )
            except FetchNotRead as error:
                log.info("session %s: its parts are relayed: %s", agent_session_id, error)
                await pool_directory.write(
                    transport,
                    held,
                    pool_archive.parts(buckets, ctx, agent_session_id, archive),
                    epoch=epoch,
                )
        else:
            packing = pool_directory.TAR
            count = await pool_directory.write(
                transport, held, snapshots.parts(ctx, agent_session_id, archive), epoch=epoch
            )
        await pool_directory.unpack(
            ctx,
            transport,
            record_seal,
            held,
            parts=count,
            packing=packing,
            epoch=epoch,
            within=self._pack_within,
            now=self._clock(),
        )

    async def _recycled(self, ctx: TenantContext, agent_session_id: UUID) -> None:
        """The session's VM let go if it is past its age. One that does not
        go stays as it was, for a later run's end or the sweep past the
        grace: the run has ended either way."""
        assert self._cloud is not None
        try:
            await self._cloud.recycle(ctx, agent_session_id)
        except Exception:
            log.exception("session %s: its VM past its age was not let go", agent_session_id)

    async def _snapshot_on_vm(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        workspace: AgentWorkspace,
        *,
        epoch: int,
        loop_id: UUID,
        tools: Sequence[ToolInterface],
    ) -> AgentStep:
        """The VM's directory, kept as the session's snapshot once what the
        workspace holds is pushed, while its host still runs, and the step
        that names it. Refused before anything is packed when the session
        keeps no content at rest. The directory is packed and compressed in
        the VM and measured there, refused past the bound before any byte
        leaves, scanned for an injected secret's value, then read out
        through the relay, part by part, each sealed under a key of its own
        and kept in the platform's bucket, with the archive that keeps those
        keys under the session's (`pool_archive.keep`): one that fails part
        way keeps no part, and the snapshot before stays the latest. The
        pack goes from the VM however it ends. The pool records the
        session's archives first, so none is ever kept unswept. The release
        then lets the VM go, and keeps no disk of it."""
        assert self._cloud is not None
        snapshots, buckets, transport, record_seal = self._archives()
        await snapshots.at_rest(ctx, agent_session_id)
        await self._agent_workspaces.detach(ctx, workspace, epoch)
        await self._cloud.archived(ctx, agent_session_id)
        also = injected_secrets(tool.spec for tool in tools)
        try:
            packed, packing = await pool_directory.pack(
                ctx,
                transport,
                record_seal,
                workspace,
                bound=snapshots.directory_bound,
                epoch=epoch,
                within=self._pack_within,
                now=self._clock(),
            )
            snapshots.bounded(packed.size)

            def read(part_bytes: int) -> AsyncGenerator[bytes]:
                return pool_directory.read(transport, workspace, packed, part_bytes)

            bound = snapshots.directory_bound
            async with (
                contextlib.aclosing(read(snapshots.part_bytes)) as held,
                contextlib.aclosing(pool_directory.unpacked(held, packing, bound)) as tar,
            ):
                await snapshots.scan(ctx, tar, also=also)
            kept = await pool_archive.keep(
                snapshots,
                buckets,
                ctx,
                agent_session_id,
                new_id(),
                workspace.id,
                size=packed.size,
                packing=packing,
                read=read,
            )
        finally:
            await self._dropped(ctx, workspace, epoch)
        await self._recorded(ctx, agent_session_id, kept)
        # From here the directory is kept: the release lets the VM go.
        self._archived.add(agent_session_id)
        step = snapshotted_step(new_id(), self._clock(), agent_session_id, loop_id, kept)
        (stored,) = await self._steps.append_agent_steps(ctx, agent_session_id, epoch, [step])
        return stored

    async def _dropped(self, ctx: TenantContext, workspace: AgentWorkspace, epoch: int) -> None:
        """The pack gone from the VM, or logged: a pack left there goes
        with the VM at the release, or at the next pack."""
        _, _, transport, record_seal = self._archives()
        try:
            await pool_directory.drop(
                ctx,
                transport,
                record_seal,
                workspace,
                epoch=epoch,
                within=self._pack_within,
                now=self._clock(),
            )
        except Exception:
            log.warning("session %s: its VM keeps a pack", workspace.id, exc_info=True)

    def _archives(
        self,
    ) -> tuple[SnapshotStore, BucketsInterface, TransportInterface, RecordSealInterface]:
        """What keeps a VM's directory of the cloud pool: the platform's
        bucket, and the transport that reaches its host. A process that
        wires none keeps none (`SnapshotRefused`)."""
        if (
            self._snapshots is None
            or self._buckets is None
            or self._transport is None
            or self._record_seal is None
        ):
            raise SnapshotRefused(
                "this process reaches no VM's directory of the cloud pool, so it keeps none"
            )
        return self._snapshots, self._buckets, self._transport, self._record_seal

    async def _recorded(
        self, ctx: TenantContext, agent_session_id: UUID, taken: AgentWorkspaceSnapshot
    ) -> None:
        """Records that a snapshot this process kept lives in the platform's
        bucket. The step names it either way, and a snapshot with no record
        is read from the bucket, so a record that fails to land loses
        nothing: it is logged."""
        now = self._clock()
        record = KeptSnapshot(
            id=taken.id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            agent_session_id=agent_session_id,
            hash=taken.hash,
            size=taken.size,
            reference=snapshot_key(agent_session_id, taken.hash),
        )
        try:
            await self._agent_workspaces.keep_snapshot(ctx, record)
        except Exception:
            log.exception(
                "session %s: where snapshot %s lives was not recorded", agent_session_id, taken.id
            )

    async def _in_store(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        pool_id: UUID,
        restore: AgentWorkspaceSnapshot,
    ) -> HostSnapshot:
        """The snapshot a restore of a session inside its tenant's wall starts
        from, as the store of a host of its pool keeps it. One the platform's
        bucket keeps never crosses into the wall, one another pool keeps is
        out of reach, and one whose record does not match the step that names
        it is not trusted: each loses the workspace (`AgentWorkspaceLost`)."""
        record = await self._agent_workspaces.kept_snapshot(ctx, restore.id)
        what = f"snapshot {restore.id} of session {agent_session_id}"
        if record is None or not record.on_host:
            raise AgentWorkspaceLost(
                f"{what} is kept in the platform's bucket, which never crosses into the wall"
            )
        if record.pool_id != pool_id:
            raise AgentWorkspaceLost(f"{what} is kept inside another pool's wall, out of reach")
        if (record.agent_session_id, record.hash, record.size) != (
            agent_session_id,
            restore.hash,
            restore.size,
        ):
            raise AgentWorkspaceLost(f"{what} is not the one its record names")
        return HostSnapshot(
            id=record.id,
            reference=record.reference,
            digest=record.digest,
            size=record.size,
            kept_by=record.host_id,
        )

    async def _in_bucket(
        self, ctx: TenantContext, agent_session_id: UUID, restore: AgentWorkspaceSnapshot
    ) -> None:
        """Holds a restore this process makes to a snapshot of the platform's
        bucket: one a host keeps inside its tenant's wall never leaves it,
        so a workspace made here cannot start from it (`AgentWorkspaceLost`)."""
        record = await self._agent_workspaces.kept_snapshot(ctx, restore.id)
        if record is not None and record.on_host:
            raise AgentWorkspaceLost(
                f"snapshot {restore.id} is kept inside the wall of pool {record.pool_id}, "
                f"which session {agent_session_id}'s workspace does not run in"
            )

    # The engine's, unchanged.

    async def get_policy(self, ctx: TenantContext) -> ToolPolicy:
        return await self._inner.get_policy(ctx)

    async def write_policy(self, ctx: TenantContext, policy: ToolPolicy) -> ToolPolicy:
        return await self._inner.write_policy(ctx, policy)

    async def input_hash(
        self, ctx: TenantContext, agent_session_id: UUID, call_input: Mapping[str, Any]
    ) -> str:
        return await self._inner.input_hash(ctx, agent_session_id, call_input)

    async def gate(
        self,
        ctx: TenantContext,
        registry: ToolRegistry,
        defaults: ToolPolicyLayer,
        request: AgentStep,
        call_input: Mapping[str, Any],
        workspace: AgentWorkspace,
        *,
        egress: EgressMode,
        holds_private: bool = True,
        tree_deadline: datetime | None = None,
        above: Sequence[ToolPolicyLayer] = (),
    ) -> Gate:
        return await self._inner.gate(
            ctx,
            registry,
            defaults,
            request,
            call_input,
            workspace,
            egress=await self._pinned_egress(ctx, request, workspace, egress),
            holds_private=holds_private,
            tree_deadline=tree_deadline,
            above=above,
        )

    async def _pinned_egress(
        self, ctx: TenantContext, request: AgentStep, workspace: AgentWorkspace, asked: EgressMode
    ) -> EgressMode:
        """The session's egress as its pin holds it, which the rule of two
        reads whatever workspace the call was given: an agent project's
        allowlist may open egress its kind holds to its hosts, or close what
        its kind opens. A prepared workspace holds the pin; a session never
        pinned holds what its kind asks."""
        if workspace.spec.mode is not IsolationMode.NONE:
            return workspace.spec.egress.mode
        try:
            pin = await self._agent_workspaces.get_workspace(ctx, request.agent_session_id)
        except NotFound:
            return asked
        return pin.egress

    async def execute(
        self,
        ctx: TenantContext,
        registry: ToolRegistry,
        request: AgentStep,
        call_input: Mapping[str, Any],
        workspace: AgentWorkspace,
        *,
        epoch: int,
        tree_deadline: datetime | None,
        on_output: OutputSink | None = None,
        kept_as: Mapping[str, str] | None = None,
    ) -> AgentStep:
        return await self._inner.execute(
            ctx,
            registry,
            request,
            call_input,
            workspace,
            epoch=epoch,
            tree_deadline=tree_deadline,
            on_output=on_output,
            kept_as=kept_as,
        )

    async def recover(
        self,
        ctx: TenantContext,
        registry: ToolRegistry,
        request: AgentStep,
        call_input: Mapping[str, Any],
        workspace: AgentWorkspace,
        *,
        epoch: int,
        tree_deadline: datetime | None,
        on_output: OutputSink | None = None,
        kept_as: Mapping[str, str] | None = None,
    ) -> AgentStep:
        return await self._inner.recover(
            ctx,
            registry,
            request,
            call_input,
            workspace,
            epoch=epoch,
            tree_deadline=tree_deadline,
            on_output=on_output,
            kept_as=kept_as,
        )

    async def start_job(
        self,
        ctx: TenantContext,
        registry: ToolRegistry,
        request: AgentStep,
        call_input: Mapping[str, Any],
        workspace: AgentWorkspace,
        *,
        epoch: int,
        tree_deadline: datetime | None,
        kept_as: Mapping[str, str] | None = None,
    ) -> JobHandle | JobNotStarted | AgentStep:
        return await self._inner.start_job(
            ctx,
            registry,
            request,
            call_input,
            workspace,
            epoch=epoch,
            tree_deadline=tree_deadline,
            kept_as=kept_as,
        )

    async def cancel_job(self, ctx: TenantContext, registry: ToolRegistry, job: JobHandle) -> None:
        await self._inner.cancel_job(ctx, registry, job)

    async def decide_call(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        request_seq: int,
        *,
        approve: bool,
        note: str = "",
    ) -> AgentStep:
        return await self._inner.decide_call(
            ctx, agent_session_id, request_seq, approve=approve, note=note
        )

    async def purge_tenant(self, ctx: TenantContext) -> int:
        # A deleted tenant's VMs, and the pool's records of its sessions'
        # archives, go with it.
        vms = 0 if self._cloud is None else await self._cloud.purge_tenant(ctx)
        return vms + await self._inner.purge_tenant(ctx)
