"""The tools manager as the platform runs it: the engine's, with every
workspace held to its session's pin. A prepare asks for the pinned isolation
whatever a loop asks, and the host refuses what it cannot give
(`rules.host_refusal`) before its provider is reached, so the loop parks on
the resource and no weaker place is made. A prepared workspace is brought
up to the session's branch; a release first pushes what the workspace
holds, then lets go only of what its own run holds. Every other operation is
the engine's, unchanged.

A run is named by its epoch, read from storage as it prepares: a session
that resumes on this host while the run before it is still being released
is the later run's from the moment its prepare starts here, so the earlier
release leaves its instance, and what this host holds of it, to the later
one. A later run on another host makes its own there, and this host's goes.

The host is this process: what it offers and how many directory sessions it
holds live are its own, never the control plane's. A session that runs
inside its tenant's wall is the exception: its workspace is the one the host
of its pool holds (`PlacedWorkspacesInterface`), which this process neither
makes nor lets go, and its checkout runs there through the relay."""

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from acme.infra.transports import OutputSink
from acme.infra.workspaces import IsolationMode, IsolationRefused, IsolationSpec, Workspace
from acme.om.context import TenantContext
from acme.om.steps import StepsManagerInterface
from acme.om.steps.types.step import Step
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.tools.registry import ToolRegistry
from acme.om.tools.types.call import Gate, JobHandle
from acme.om.tools.types.policy import PolicyLayer, ToolPolicy
from acme.om.workspaces.manager import WorkspacesManagerInterface
from acme.om.workspaces.placed import PlacedWorkspacesInterface
from acme.om.workspaces.rules import host_refusal
from acme.om.workspaces.types.host import HostOffer

log = logging.getLogger(__name__)


class HeldWorkspaces:
    """The workspaces this host holds prepared, by session, each under the
    epoch of the run that prepared it: from a prepare that succeeded to the
    release that let it go. What a session delivered is read from the one it
    holds (`WorkProductWorkspacesImpl`)."""

    def __init__(self) -> None:
        self._held: dict[UUID, tuple[Workspace, int]] = {}

    def get(self, session_id: UUID) -> Workspace | None:
        held = self._held.get(session_id)
        return None if held is None else held[0]

    def epoch_of(self, session_id: UUID) -> int | None:
        """The epoch of the run that holds the session's workspace here."""
        held = self._held.get(session_id)
        return None if held is None else held[1]

    def hold(self, workspace: Workspace, epoch: int) -> None:
        self._held[workspace.id] = (workspace, epoch)

    def let_go(self, session_id: UUID, epoch: int | None = None) -> None:
        """Lets the session's workspace go: with an epoch, only when the run
        of that epoch still holds it, so a later run's stays."""
        if epoch is None or self.epoch_of(session_id) == epoch:
            self._held.pop(session_id, None)


class ToolsManagerWorkspacesImpl(ToolsManagerInterface):
    def __init__(
        self,
        inner: ToolsManagerInterface,
        workspaces: WorkspacesManagerInterface,
        steps: StepsManagerInterface,
        offer: HostOffer,
        *,
        local: bool,
        held: HeldWorkspaces | None = None,
        placed: PlacedWorkspacesInterface | None = None,
    ) -> None:
        self._inner = inner
        self._workspaces = workspaces
        self._steps = steps
        self._offer = offer
        self._local = local
        self._held = held or HeldWorkspaces()
        self._placed = placed
        # The directory workspaces live here, each under its run's epoch.
        self._directories: dict[UUID, int] = {}
        self._hosted: set[UUID] = set()  # the workspaces a host of the tenant's holds
        self._preparing: dict[UUID, int] = {}  # the prepares under way here, by session

    # The workspace.

    async def prepare_workspace(
        self, ctx: TenantContext, session_id: UUID, spec: IsolationSpec
    ) -> Workspace:
        # Marked before the first await, and until the workspace is held: a
        # release that lands meanwhile leaves the instance to this run.
        self._preparing[session_id] = self._preparing.get(session_id, 0) + 1
        try:
            return await self._prepare(ctx, session_id, spec)
        finally:
            left = self._preparing.pop(session_id) - 1
            if left:
                self._preparing[session_id] = left

    async def _prepare(
        self, ctx: TenantContext, session_id: UUID, spec: IsolationSpec
    ) -> Workspace:
        pinned = await self._workspaces.pinned(ctx, session_id, spec)
        if pinned.mode is IsolationMode.NONE:
            return await self._inner.prepare_workspace(ctx, session_id, pinned)
        # The run that prepares it took its epoch just before: what this
        # host holds for the session is held under it.
        epoch = (await self._steps.get_cursor(ctx, session_id)).epoch
        if self._placed is not None:
            hosted = await self._placed.held_on_host(ctx, session_id, pinned)
            if hosted is not None:
                # Its host made it to the pin and holds it; the checkout is
                # brought up to the session's branch there.
                attached = await self._workspaces.attach(ctx, hosted)
                self._hosted.add(session_id)
                self._held.hold(attached, epoch)
                return attached
        running = len(self._directories.keys() - {session_id})
        why = host_refusal(pinned, self._offer, local=self._local, running=running)
        if why is not None:
            raise IsolationRefused(why)
        # Held before the first await, so two prepares at once count each
        # other.
        if pinned.mode is IsolationMode.HOST:
            self._directories[session_id] = epoch
        try:
            workspace = await self._inner.prepare_workspace(ctx, session_id, pinned)
        except BaseException:
            self._directories.pop(session_id, None)
            raise
        try:
            attached = await self._workspaces.attach(ctx, workspace)
        except BaseException:
            # Its instance goes, and its files stay as they were: nothing of
            # the loop ran in it.
            try:
                await self._inner.release_workspace(ctx, workspace)
            except Exception:
                log.exception("session %s: the workspace was not released", session_id)
            self._directories.pop(session_id, None)
            raise
        self._held.hold(attached, epoch)
        return attached

    async def release_workspace(self, ctx: TenantContext, workspace: Workspace) -> None:
        # The run that releases it holds it until here: a later run's
        # prepare cannot land before its first await.
        epoch = self._held.epoch_of(workspace.id)
        if workspace.spec.mode is not IsolationMode.NONE:
            # Kept first: a push that does not land raises, and the instance
            # and its work stay.
            await self._workspaces.detach(ctx, workspace)
        if epoch is not None and self._taken_here(workspace.id, epoch):
            # The session resumed here while its work was kept: the instance
            # is the later run's, to let go when it ends.
            log.info("session %s: a later run holds its workspace, which stays", workspace.id)
        elif workspace.id in self._hosted:
            # Its host holds it, warm for the next loop: nothing of this
            # process's goes.
            self._hosted.discard(workspace.id)
        else:
            await self._inner.release_workspace(ctx, workspace)
        if epoch is not None:
            # Only what this run holds: a later run's stays held.
            self._held.let_go(workspace.id, epoch)
            if self._directories.get(workspace.id) == epoch:
                del self._directories[workspace.id]

    def _taken_here(self, session_id: UUID, epoch: int) -> bool:
        """Whether a later run in this process prepares the session's
        workspace or holds it. One on another host, or one that never
        prepares, takes nothing of this host's."""
        held = self._held.epoch_of(session_id)
        return session_id in self._preparing or (held is not None and held != epoch)

    async def purge_workspace(self, org_id: UUID, session_id: UUID) -> None:
        await self._inner.purge_workspace(org_id, session_id)
        self._held.let_go(session_id)
        self._directories.pop(session_id, None)
        self._hosted.discard(session_id)

    # The engine's, unchanged.

    async def get_policy(self, ctx: TenantContext) -> ToolPolicy:
        return await self._inner.get_policy(ctx)

    async def write_policy(self, ctx: TenantContext, policy: ToolPolicy) -> ToolPolicy:
        return await self._inner.write_policy(ctx, policy)

    async def input_hash(
        self, ctx: TenantContext, session_id: UUID, call_input: Mapping[str, Any]
    ) -> str:
        return await self._inner.input_hash(ctx, session_id, call_input)

    async def gate(
        self,
        ctx: TenantContext,
        registry: ToolRegistry,
        defaults: PolicyLayer,
        request: Step,
        call_input: Mapping[str, Any],
        workspace: Workspace,
        *,
        holds_private: bool = True,
        tree_deadline: datetime | None = None,
    ) -> Gate:
        return await self._inner.gate(
            ctx,
            registry,
            defaults,
            request,
            call_input,
            workspace,
            holds_private=holds_private,
            tree_deadline=tree_deadline,
        )

    async def execute(
        self,
        ctx: TenantContext,
        registry: ToolRegistry,
        request: Step,
        call_input: Mapping[str, Any],
        workspace: Workspace,
        *,
        epoch: int,
        tree_deadline: datetime | None,
        on_output: OutputSink | None = None,
        kept_as: Mapping[str, str] | None = None,
    ) -> Step:
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
        request: Step,
        call_input: Mapping[str, Any],
        workspace: Workspace,
        *,
        epoch: int,
        tree_deadline: datetime | None,
        on_output: OutputSink | None = None,
        kept_as: Mapping[str, str] | None = None,
    ) -> Step:
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
        request: Step,
        call_input: Mapping[str, Any],
        workspace: Workspace,
        *,
        epoch: int,
        tree_deadline: datetime | None,
        kept_as: Mapping[str, str] | None = None,
    ) -> JobHandle | Step:
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
        session_id: UUID,
        request_seq: int,
        *,
        approve: bool,
        note: str = "",
    ) -> Step:
        return await self._inner.decide_call(
            ctx, session_id, request_seq, approve=approve, note=note
        )

    async def purge_tenant(self, ctx: TenantContext) -> int:
        return await self._inner.purge_tenant(ctx)
