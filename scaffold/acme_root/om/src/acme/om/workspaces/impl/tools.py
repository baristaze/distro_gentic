"""The tools manager as the platform runs it: the engine's, with every
workspace held to its session's pin. A prepare asks for the pinned isolation
whatever a loop asks, and the host refuses what it cannot give
(`rules.host_refusal`) before its provider is reached, so the loop parks on
the resource and no weaker place is made. A prepared workspace is brought
up to the session's branch; a release first pushes what the workspace
holds. Every other operation is the engine's, unchanged.

The host is this process: what it offers and how many directory sessions it
holds live are its own, never the control plane's."""

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from acme.infra.transports import OutputSink
from acme.infra.workspaces import IsolationMode, IsolationRefused, IsolationSpec, Workspace
from acme.om.context import TenantContext
from acme.om.steps.types.step import Step
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.tools.registry import ToolRegistry
from acme.om.tools.types.call import Gate, JobHandle
from acme.om.tools.types.policy import PolicyLayer, ToolPolicy
from acme.om.workspaces.manager import WorkspacesManagerInterface
from acme.om.workspaces.rules import host_refusal
from acme.om.workspaces.types.host import HostOffer

log = logging.getLogger(__name__)


class HeldWorkspaces:
    """The workspaces this host holds prepared, by session: from a prepare
    that succeeded to the release that let it go. What a session delivered
    is read from the one it holds (`WorkProductWorkspacesImpl`)."""

    def __init__(self) -> None:
        self._held: dict[UUID, Workspace] = {}

    def get(self, session_id: UUID) -> Workspace | None:
        return self._held.get(session_id)

    def hold(self, workspace: Workspace) -> None:
        self._held[workspace.id] = workspace

    def let_go(self, session_id: UUID) -> None:
        self._held.pop(session_id, None)


class ToolsManagerWorkspacesImpl(ToolsManagerInterface):
    def __init__(
        self,
        inner: ToolsManagerInterface,
        workspaces: WorkspacesManagerInterface,
        offer: HostOffer,
        *,
        local: bool,
        held: HeldWorkspaces | None = None,
    ) -> None:
        self._inner = inner
        self._workspaces = workspaces
        self._offer = offer
        self._local = local
        self._held = held or HeldWorkspaces()
        self._directories: set[UUID] = set()  # the directory workspaces live here

    # The workspace.

    async def prepare_workspace(
        self, ctx: TenantContext, session_id: UUID, spec: IsolationSpec
    ) -> Workspace:
        pinned = await self._workspaces.pinned(ctx, session_id, spec)
        if pinned.mode is IsolationMode.NONE:
            return await self._inner.prepare_workspace(ctx, session_id, pinned)
        running = len(self._directories - {session_id})
        why = host_refusal(pinned, self._offer, local=self._local, running=running)
        if why is not None:
            raise IsolationRefused(why)
        # Held before the first await, so two prepares at once count each
        # other.
        if pinned.mode is IsolationMode.HOST:
            self._directories.add(session_id)
        try:
            workspace = await self._inner.prepare_workspace(ctx, session_id, pinned)
        except BaseException:
            self._directories.discard(session_id)
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
            self._directories.discard(session_id)
            raise
        self._held.hold(attached)
        return attached

    async def release_workspace(self, ctx: TenantContext, workspace: Workspace) -> None:
        if workspace.spec.mode is not IsolationMode.NONE:
            # Kept first: a push that does not land raises, and the instance
            # and its work stay.
            await self._workspaces.detach(ctx, workspace)
        await self._inner.release_workspace(ctx, workspace)
        self._held.let_go(workspace.id)
        self._directories.discard(workspace.id)

    async def purge_workspace(self, org_id: UUID, session_id: UUID) -> None:
        await self._inner.purge_workspace(org_id, session_id)
        self._held.let_go(session_id)
        self._directories.discard(session_id)

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
