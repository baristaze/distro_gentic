"""The tools manager with the gates of a session's playbooks around every
call. The gates only narrow: a call a gate denies is refused whatever the
policy beneath says, and a call a gate holds for approval runs only on a
person's approval of exactly that call, as the tenant's approvers decide
it. A call the policy beneath refuses or holds stays refused or held."""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from acme.infra.transports import OutputSink
from acme.infra.workspaces import IsolationSpec, Workspace
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.exceptions import NotFound
from acme.om.playbooks.manager import PlaybooksManagerInterface
from acme.om.playbooks.rules import narrowed
from acme.om.steps import StepsManagerInterface
from acme.om.steps.types.header import ToolFailure, ToolRequestHeader
from acme.om.steps.types.step import Step
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.tools.registry import ToolRegistry
from acme.om.tools.rules import approver_roles, response, strictest, verdict
from acme.om.tools.types.call import Gate, GateOutcome, JobHandle, JobNotStarted, Verdict
from acme.om.tools.types.policy import Decision, PolicyLayer, ToolPolicy

REFUSAL_CHARS = 2_000
HISTORY_PAGE = 200


class ToolsManagerPlaybooksImpl(ToolsManagerInterface):
    """`playbooks` and `steps` answer at call time: a root builds this layer
    before the managers it reads."""

    def __init__(
        self,
        inner: ToolsManagerInterface,
        playbooks: Callable[[], PlaybooksManagerInterface],
        steps: Callable[[], StepsManagerInterface],
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._inner = inner
        self._playbooks = playbooks
        self._steps = steps
        self._clock = clock

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
        request: Step,
        call_input: Mapping[str, Any],
        workspace: Workspace,
        *,
        epoch: int,
        tree_deadline: datetime | None,
        on_output: OutputSink | None = None,
        kept_as: Mapping[str, str] | None = None,
    ) -> Step:
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
        request: Step,
        call_input: Mapping[str, Any],
        workspace: Workspace,
        *,
        epoch: int,
        tree_deadline: datetime | None,
        on_output: OutputSink | None = None,
        kept_as: Mapping[str, str] | None = None,
    ) -> Step:
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
        request: Step,
        call_input: Mapping[str, Any],
        workspace: Workspace,
        *,
        epoch: int,
        tree_deadline: datetime | None,
        kept_as: Mapping[str, str] | None = None,
    ) -> JobHandle | JobNotStarted | Step:
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

    async def prepare_workspace(
        self, ctx: TenantContext, session_id: UUID, spec: IsolationSpec
    ) -> Workspace:
        return await self._inner.prepare_workspace(ctx, session_id, spec)

    async def release_workspace(self, ctx: TenantContext, workspace: Workspace) -> None:
        await self._inner.release_workspace(ctx, workspace)

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

    async def purge_tenant(self, ctx: TenantContext) -> int:
        return await self._inner.purge_tenant(ctx)

    # Helpers.

    async def _narrowed(self, ctx: TenantContext, request: Step, decided: Decision) -> Decision:
        header = request.header
        if not isinstance(header, ToolRequestHeader):
            return decided
        try:
            gates = await self._playbooks().gates_of(ctx, request.session_id)
        except NotFound:
            # A session of its chain cannot be read, nor the gates it
            # invoked: the call waits for a person rather than run past them.
            return strictest(decided, Decision.APPROVE)
        return narrowed(decided, gates, header.tool, header.authorization_class)

    async def _approvers(self, ctx: TenantContext, request: Step) -> tuple[Any, ...]:
        header = request.header
        assert isinstance(header, ToolRequestHeader)
        return approver_roles(await self._inner.get_policy(ctx), header.authorization_class)

    async def _after(self, ctx: TenantContext, request: Step) -> list[Step]:
        later: list[Step] = []
        after = request.seq
        while True:
            page = await self._steps().get_steps(ctx, request.session_id, after, HISTORY_PAGE)
            later += page.items
            if not page.has_more or not page.items:
                return later
            after = page.items[-1].seq

    def _denied(self, request: Step) -> Step:
        header = request.header
        tool = header.tool if isinstance(header, ToolRequestHeader) else "this tool"
        return self._answer(
            request, f"a playbook of this session does not allow {tool}", ToolFailure.DENIED
        )

    def _answer(self, request: Step, text: str, failure: ToolFailure) -> Step:
        return response(new_id(), self._clock(), request, text, failure, limit=REFUSAL_CHARS)
