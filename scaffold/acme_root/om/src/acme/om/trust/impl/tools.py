"""The tools manager as the platform runs it: the engine's, with the trust
swimlane's two rules around every call. A call whose tool would use a
secret on the far side of its session's wall is refused, at its gate and
again before it runs, and never reaches a transport. And every call that
runs has its audit entry written first, with its four answers apart."""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from acme.infra.transports import OutputSink
from acme.infra.workspaces import IsolationSpec, Workspace
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.steps.types.header import ToolFailure, ToolRequestHeader, WorkspaceSnapshot
from acme.om.steps.types.step import Step
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.tools.registry import ToolRegistry
from acme.om.tools.rules import response
from acme.om.tools.tool import TakenSnapshot
from acme.om.tools.types.call import Gate, GateOutcome, JobHandle, JobNotStarted
from acme.om.tools.types.policy import PolicyLayer, ToolPolicy
from acme.om.trust.exceptions import SecretCrossesWall
from acme.om.trust.manager import TrustManagerInterface

REFUSAL_CHARS = 2_000
"""What the model reads of a refusal, at most: a secret's name and why."""


class ToolsManagerTrustedImpl(ToolsManagerInterface):
    """`trust` answers the trust manager at call time: a root builds this
    layer before the trust manager, which reads the managers this layer is
    one of. Where a call's secrets are kept is this layer's answer alone:
    a `kept_as` it is handed is never passed on."""

    def __init__(
        self,
        inner: ToolsManagerInterface,
        trust: Callable[[], TrustManagerInterface],
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._inner = inner
        self._trust = trust
        self._clock = clock

    # The calls, held to the wall and audited.

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
        above: Sequence[PolicyLayer] = (),
    ) -> Gate:
        resolved = await self._resolved(ctx, registry, request)
        if isinstance(resolved, Step):
            return Gate(outcome=GateOutcome.REFUSE, response=resolved)
        return await self._inner.gate(
            ctx,
            registry,
            defaults,
            request,
            call_input,
            workspace,
            holds_private=holds_private,
            tree_deadline=tree_deadline,
            above=above,
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
        resolved = await self._resolved(ctx, registry, request)
        if isinstance(resolved, Step):
            return resolved
        await self._trust().audit_call(ctx, request)
        return await self._inner.execute(
            ctx,
            registry,
            request,
            call_input,
            workspace,
            epoch=epoch,
            tree_deadline=tree_deadline,
            on_output=on_output,
            kept_as=resolved,
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
        resolved = await self._resolved(ctx, registry, request)
        if isinstance(resolved, Step):
            return resolved
        await self._trust().audit_call(ctx, request)
        return await self._inner.recover(
            ctx,
            registry,
            request,
            call_input,
            workspace,
            epoch=epoch,
            tree_deadline=tree_deadline,
            on_output=on_output,
            kept_as=resolved,
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
    ) -> JobHandle | JobNotStarted | Step:
        resolved = await self._resolved(ctx, registry, request)
        if isinstance(resolved, Step):
            # Refused before its tool ran: nothing started.
            return JobNotStarted(response=resolved)
        await self._trust().audit_call(ctx, request)
        return await self._inner.start_job(
            ctx,
            registry,
            request,
            call_input,
            workspace,
            epoch=epoch,
            tree_deadline=tree_deadline,
            kept_as=resolved,
        )

    # The rest, as the engine's.

    async def get_policy(self, ctx: TenantContext) -> ToolPolicy:
        return await self._inner.get_policy(ctx)

    async def write_policy(self, ctx: TenantContext, policy: ToolPolicy) -> ToolPolicy:
        return await self._inner.write_policy(ctx, policy)

    async def prepare_workspace(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spec: IsolationSpec,
        restore: WorkspaceSnapshot | None = None,
    ) -> Workspace:
        return await self._inner.prepare_workspace(ctx, session_id, spec, restore)

    async def release_workspace(self, ctx: TenantContext, workspace: Workspace) -> None:
        await self._inner.release_workspace(ctx, workspace)

    async def snapshot_workspace(
        self,
        ctx: TenantContext,
        session_id: UUID,
        workspace: Workspace,
        *,
        epoch: int,
        loop_id: UUID,
    ) -> Step:
        return await self._inner.snapshot_workspace(
            ctx, session_id, workspace, epoch=epoch, loop_id=loop_id
        )

    async def fork_snapshot(
        self, ctx: TenantContext, child_id: UUID, snapshot_id: UUID, taken: TakenSnapshot
    ) -> WorkspaceSnapshot:
        return await self._inner.fork_snapshot(ctx, child_id, snapshot_id, taken)

    async def find_snapshot(
        self, ctx: TenantContext, session_id: UUID, snapshot_id: UUID
    ) -> WorkspaceSnapshot:
        return await self._inner.find_snapshot(ctx, session_id, snapshot_id)

    async def input_hash(
        self, ctx: TenantContext, session_id: UUID, call_input: Mapping[str, Any]
    ) -> str:
        return await self._inner.input_hash(ctx, session_id, call_input)

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

    async def purge_workspace(self, org_id: UUID, session_id: UUID) -> None:
        await self._inner.purge_workspace(org_id, session_id)

    async def erase_snapshots(self, ctx: TenantContext, session_id: UUID) -> None:
        await self._inner.erase_snapshots(ctx, session_id)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        return await self._inner.purge_tenant(ctx)

    # Helpers.

    async def _resolved(
        self, ctx: TenantContext, registry: ToolRegistry, request: Step
    ) -> Step | dict[str, str]:
        """The name the tenant's store keeps each of the call's secrets
        under, for its session; or the `denied` answer to a call whose tool
        declares a secret that would cross its session's wall. A tool's
        declared secrets are every secret its commands may name, so none of
        them crosses."""
        header = request.header
        if not isinstance(header, ToolRequestHeader):
            return {}
        tool = registry.get(header.tool)
        if tool is None or not tool.spec.secrets:
            return {}
        try:
            return await self._trust().resolve_secrets(ctx, request.session_id, tool.spec.secrets)
        except SecretCrossesWall as refused:
            return response(
                new_id(),
                self._clock(),
                request,
                refused.message,
                ToolFailure.DENIED,
                limit=REFUSAL_CHARS,
            )
