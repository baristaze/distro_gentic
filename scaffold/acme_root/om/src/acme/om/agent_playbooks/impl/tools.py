"""The tools manager with the gates of a session's agent playbooks around every
call. The gates only narrow: a call a gate denies is refused whatever the
policy beneath says, and a call a gate holds for approval runs only on a
person's approval of exactly that call, as the tenant's approvers decide
it. A call the policy beneath refuses or holds stays refused or held."""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from acme.infra.agent_workspaces import IsolationSpec, AgentWorkspace
from acme.infra.transports import OutputSink
from acme.om.agent_playbooks.manager import AgentPlaybooksManagerInterface
from acme.om.agent_playbooks.rules import narrowed
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agent_steps.types.header import AgentWorkspaceSnapshot, ToolFailure, ToolRequestHeader
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.exceptions import NotFound
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.tools.registry import ToolRegistry
from acme.om.tools.rules import approver_roles, response, strictest, verdict
from acme.om.tools.tool import TakenSnapshot
from acme.om.tools.types.call import Gate, GateOutcome, JobHandle, JobNotStarted, Verdict
from acme.om.tools.types.policy import Decision, ToolPolicy, ToolPolicyLayer

REFUSAL_CHARS = 2_000
HISTORY_PAGE = 200


class ToolsManagerAgentPlaybooksImpl(ToolsManagerInterface):
    """`agent_playbooks` and `steps` answer at call time: a root builds this layer
    before the managers it reads."""

    def __init__(
        self,
        inner: ToolsManagerInterface,
        agent_playbooks: Callable[[], AgentPlaybooksManagerInterface],
        steps: Callable[[], AgentStepsManagerInterface],
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._inner = inner
        self._agent_playbooks = agent_playbooks
        self._steps = steps
        self._clock = clock

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
        beneath = await self._inner.gate(
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
        if beneath.outcome is not GateOutcome.RUN:
            return beneath
        decided = beneath.decision or Decision.ALLOW
        stands = await self._narrowed(ctx, request, decided)
        if stands is Decision.DENY:
            return Gate(outcome=GateOutcome.REFUSE, decision=stands, response=self._denied(request))
        if stands is decided:
            # No gate holds it past policy: as it ran beneath, approval and all.
            return beneath
        approvers = await self._approvers(ctx, request)
        found, _ = verdict(request, await self._after(ctx, request), self._clock(), approvers)
        if found is Verdict.APPROVED:
            return beneath
        if found is Verdict.DENIED:
            denied = self._answer(request, "a person denied this call", ToolFailure.DENIED)
            return Gate(outcome=GateOutcome.REFUSE, decision=stands, response=denied)
        return Gate(outcome=GateOutcome.ASK, decision=stands, authority=beneath.authority)

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
        if await self._narrowed(ctx, request, Decision.ALLOW) is Decision.DENY:
            return self._denied(request)
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
        if await self._narrowed(ctx, request, Decision.ALLOW) is Decision.DENY:
            return self._denied(request)
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
        if await self._narrowed(ctx, request, Decision.ALLOW) is Decision.DENY:
            # Refused before its tool ran: nothing started.
            return JobNotStarted(response=self._denied(request))
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

    # The rest, as beneath.

    async def get_policy(self, ctx: TenantContext) -> ToolPolicy:
        return await self._inner.get_policy(ctx)

    async def write_policy(self, ctx: TenantContext, policy: ToolPolicy) -> ToolPolicy:
        return await self._inner.write_policy(ctx, policy)

    async def prepare_agent_workspace(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        restore: AgentWorkspaceSnapshot | None = None,
    ) -> AgentWorkspace:
        return await self._inner.prepare_agent_workspace(ctx, agent_session_id, spec, restore)

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

    # Helpers.

    async def _narrowed(self, ctx: TenantContext, request: AgentStep, decided: Decision) -> Decision:
        header = request.header
        if not isinstance(header, ToolRequestHeader):
            return decided
        try:
            gates = await self._agent_playbooks().gates_of(ctx, request.agent_session_id)
        except NotFound:
            # A session of its chain cannot be read, nor the gates it
            # invoked: the call waits for a person rather than run past them.
            return strictest(decided, Decision.APPROVE)
        return narrowed(decided, gates, header.tool, header.authorization_class)

    async def _approvers(self, ctx: TenantContext, request: AgentStep) -> tuple[Any, ...]:
        header = request.header
        assert isinstance(header, ToolRequestHeader)
        return approver_roles(await self._inner.get_policy(ctx), header.authorization_class)

    async def _after(self, ctx: TenantContext, request: AgentStep) -> list[AgentStep]:
        later: list[AgentStep] = []
        after = request.seq
        while True:
            page = await self._steps().get_agent_steps(
                ctx, request.agent_session_id, after, HISTORY_PAGE
            )
            later += page.items
            if not page.has_more or not page.items:
                return later
            after = page.items[-1].seq

    def _denied(self, request: AgentStep) -> AgentStep:
        header = request.header
        tool = header.tool if isinstance(header, ToolRequestHeader) else "this tool"
        return self._answer(
            request, f"an agent playbook of this session does not allow {tool}", ToolFailure.DENIED
        )

    def _answer(self, request: AgentStep, text: str, failure: ToolFailure) -> AgentStep:
        return response(new_id(), self._clock(), request, text, failure, limit=REFUSAL_CHARS)
