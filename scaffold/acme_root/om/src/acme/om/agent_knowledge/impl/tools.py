"""The tools manager that recalls a session's agent knowledge as it starts: when
the loop prepares the workspace before a session's first model call, the
reviewed entries its subject triggers arrive in it, as data, so the first
call reads them and the session does not rediscover its environment.

A session's subject is its title and what its principals said to it so
far. A session that has made a model request recalls nothing more here;
an entry recalled once is never recalled twice."""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from acme.infra.agent_workspaces import IsolationSpec, AgentWorkspace
from acme.infra.transports import OutputSink
from acme.om.agent_knowledge.manager import AgentKnowledgeManagerInterface
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agent_steps.types.header import AgentWorkspaceSnapshot
from acme.om.attribution.rules import principal_authored
from acme.om.context import TenantContext
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.tools.registry import ToolRegistry
from acme.om.tools.tool import TakenSnapshot
from acme.om.tools.types.call import Gate, JobHandle, JobNotStarted
from acme.om.tools.types.policy import ToolPolicy, ToolPolicyLayer

FIRST_STEPS = 200
"""The steps a session's subject is read from: its start, before a call."""


class ToolsManagerRecallImpl(ToolsManagerInterface):
    """`agent_knowledge`, `sessions`, and `steps` answer at call time: a root builds
    this layer before the managers it reads."""

    def __init__(
        self,
        inner: ToolsManagerInterface,
        agent_knowledge: Callable[[], AgentKnowledgeManagerInterface],
        sessions: Callable[[], AgentSessionsManagerInterface],
        steps: Callable[[], AgentStepsManagerInterface],
    ) -> None:
        self._inner = inner
        self._agent_knowledge = agent_knowledge
        self._sessions = sessions
        self._steps = steps

    async def prepare_agent_workspace(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        restore: AgentWorkspaceSnapshot | None = None,
    ) -> AgentWorkspace:
        workspace = await self._inner.prepare_agent_workspace(ctx, agent_session_id, spec, restore)
        session = await self._sessions().get_agent_session(ctx, agent_session_id)
        if session.speaker is None:
            # No model request yet: this loop starts the session.
            page = await self._steps().get_agent_steps(ctx, agent_session_id, 0, FIRST_STEPS)
            said = [step.as_text() for step in page.items if principal_authored(step)]
            await self._agent_knowledge().recall(
                ctx, agent_session_id, "\n".join([session.title, *said])
            )
        return workspace

    # The rest, as beneath.

    async def gate(
        self,
        ctx: TenantContext,
        registry: ToolRegistry,
        defaults: ToolPolicyLayer,
        request: AgentStep,
        call_input: Mapping[str, Any],
        workspace: AgentWorkspace,
        *,
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
            holds_private=holds_private,
            tree_deadline=tree_deadline,
            above=above,
        )

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

    async def get_policy(self, ctx: TenantContext) -> ToolPolicy:
        return await self._inner.get_policy(ctx)

    async def write_policy(self, ctx: TenantContext, policy: ToolPolicy) -> ToolPolicy:
        return await self._inner.write_policy(ctx, policy)

    async def release_agent_workspace(self, ctx: TenantContext, workspace: AgentWorkspace) -> None:
        await self._inner.release_agent_workspace(ctx, workspace)

    async def snapshot_agent_workspace(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        workspace: AgentWorkspace,
        *,
        epoch: int,
        loop_id: UUID,
    ) -> AgentStep:
        return await self._inner.snapshot_agent_workspace(
            ctx, agent_session_id, workspace, epoch=epoch, loop_id=loop_id
        )

    async def fork_snapshot(
        self, ctx: TenantContext, child_id: UUID, snapshot_id: UUID, taken: TakenSnapshot
    ) -> AgentWorkspaceSnapshot:
        return await self._inner.fork_snapshot(ctx, child_id, snapshot_id, taken)

    async def find_snapshot(
        self, ctx: TenantContext, agent_session_id: UUID, snapshot_id: UUID
    ) -> AgentWorkspaceSnapshot:
        return await self._inner.find_snapshot(ctx, agent_session_id, snapshot_id)

    async def input_hash(
        self, ctx: TenantContext, agent_session_id: UUID, call_input: Mapping[str, Any]
    ) -> str:
        return await self._inner.input_hash(ctx, agent_session_id, call_input)

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

    async def purge_agent_workspace(self, org_id: UUID, agent_session_id: UUID) -> None:
        await self._inner.purge_agent_workspace(org_id, agent_session_id)

    async def erase_snapshots(self, ctx: TenantContext, agent_session_id: UUID) -> None:
        await self._inner.erase_snapshots(ctx, agent_session_id)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        return await self._inner.purge_tenant(ctx)
