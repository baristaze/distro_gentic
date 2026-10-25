from typing import Any
from uuid import UUID

from pydantic import JsonValue

from acme.infra.base import thaw_mapping
from acme.integrations.model_providers.types import Usage
from acme.om.agent_projects import AgentProjectsManagerInterface
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import (
    AgentSession,
    AgentSessionPage,
    AgentSessionStatus,
    Among,
)
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agent_steps.rules import control_step, message_step
from acme.om.agent_steps.types.agent_step import AgentStep, AgentStepType
from acme.om.agent_steps.types.content import TextBlock
from acme.om.agent_steps.types.header import (
    AgentWorkspaceSnapshot,
    ControlCommand,
    ControlHeader,
    InputHeader,
    LoopEndedHeader,
    ModelResponseHeader,
    Park,
    ParkedHeader,
    SwitchedHeader,
    ToolRequestHeader,
    ToolResponseHeader,
)
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.loop import LoopManagerInterface
from acme.om.agents.types.kind import AgentKindCatalog
from acme.om.agents.types.request import Start
from acme.om.attribution import AttributionManagerInterface
from acme.om.base import utcnow
from acme.om.context import OperatorContext, TenantContext
from acme.om.exceptions import NotFound, ValidationFailed
from acme.om.spend_budgets import SpendBudgetsOperatorManagerInterface
from acme.om.spend_budgets.types.usage import AgentSessionUsage
from acme.om.tools import ToolsManagerInterface
from acme.om.tools.rules import named_snapshot
from acme.om.tools.types.call import JobCompletion
from acme.om.windows import WindowsManagerInterface
from acme.services.api.services.agent_sessions import AgentSessionsServiceInterface
from acme.services.api.services.impl.session_reads import (
    approvals_of,
    bounds_of,
    questions_of,
    tool_calls_of,
    usage_of,
    waits_on_approval,
)
from acme.services.api.services.impl.tenancy import decode_cursor, encode_cursor
from acme.services.api.types.agent_sessions import (
    MAX_SHOWN,
    AgentRefView,
    AgentSessionModelUsageView,
    AgentSessionPageView,
    AgentSessionUsageView,
    AgentSessionView,
    AgentStepPageView,
    AgentStepUsageView,
    AgentStepView,
    ApprovalPageView,
    ApprovalView,
    BoundsView,
    ControlRequest,
    DeadlineRequest,
    DecisionRequest,
    GiveBackRequest,
    JobCompletionRequest,
    MessageRequest,
    ParkView,
    PrincipalRequest,
    QuestionView,
    SnapshotView,
    StartAgentSessionRequest,
    StopReason,
    ToolCallPageView,
    ToolOutputPageView,
    ToolUseView,
    VisibilityRequest,
)
from acme.services.api.types.common import LIMIT_MAX, clamp_limit


def park_view(park: Park | None) -> ParkView | None:
    return None if park is None else ParkView.model_validate(park)


def agent_session_view(session: AgentSession) -> AgentSessionView:
    """A session as the API shows it, its title opened first: a title whose
    key is revoked says nothing, and the session keeps its place."""
    child = session.parent_id is not None
    return AgentSessionView(
        id=session.id,
        title=session.title.said(),
        kind=session.kind,
        kind_version=session.kind_version,
        status=session.status,
        park=park_view(session.park),
        parent_id=session.parent_id,
        root_id=session.root_id,
        created_at=session.created_at,
        created_by=session.created_by,
        archived_at=session.archived_at,
        deleted_at=session.deleted_at,
        visibility=session.visibility,
        participants=list(session.participants),
        steerer=None if child else session.steerer or session.created_by,
    )


SESSIONS = "agent_sessions"
CHILDREN = "agent_session_children"
APPROVALS = "approvals"
"""The lists a session cursor belongs to; each refuses the others'."""

HISTORY_PAGE = LIMIT_MAX
"""How many steps one read of a history takes, when a read folds it whole."""


def session_page(page: AgentSessionPage, listed: str) -> AgentSessionPageView:
    last = page.items[-1].id if page.items and page.has_more else None
    return AgentSessionPageView(
        items=[agent_session_view(session) for session in page.items],
        next_cursor=None if last is None else encode_cursor(listed, last),
    )


def text_of(step: AgentStep) -> str:
    """What a step says: a tool response's text parts, any other step's
    text blocks. A step whose content is gone, its session's key revoked,
    says nothing: a hole in a known place, whose shape alone stays."""
    if not step.content.is_plain():
        return ""
    if step.type is AgentStepType.TOOL_RESPONSE:
        parts = step.as_tool_response().parts
        return "\n".join(part.text for part in parts if isinstance(part, TextBlock))
    return step.as_text()


def thinking_of(step: AgentStep) -> str:
    """What a model response thought, one block a line; a redacted block
    says nothing, and neither does a step whose content is gone."""
    if not step.content.is_plain():
        return ""
    return "\n".join(block.text for block in step.children.thinking if not block.redacted)


def shown(value: Any) -> JsonValue:
    """A tool input's value as a view shows it: each string it holds cut at
    `MAX_SHOWN`, an ellipsis marking the cut."""
    if isinstance(value, str):
        return value if len(value) <= MAX_SHOWN else value[:MAX_SHOWN] + "\u2026"
    if isinstance(value, dict):
        return {str(key): shown(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shown(item) for item in value]
    return value


def tool_uses_of(step: AgentStep) -> list[ToolUseView]:
    """The calls a model response made, with what each asked; none when its
    content is gone."""
    if step.type is not AgentStepType.MODEL_RESPONSE or not step.content.is_plain():
        return []
    return [
        ToolUseView(
            id=use.id,
            name=use.name,
            input={k: shown(v) for k, v in thaw_mapping(use.input).items()},
        )
        for use in step.as_tool_uses()
    ]


def tool_use_id_of(step: AgentStep) -> str | None:
    """The call a tool step belongs to: a request's from its header, which
    stays, as its tool does; a response's from its result, gone with its
    content."""
    if isinstance(step.header, ToolRequestHeader):
        return step.header.tool_use_id
    if step.type is AgentStepType.TOOL_RESPONSE and step.content.is_plain():
        return step.as_tool_response().tool_use_id
    return None


def agent_of(step: AgentStep) -> AgentRefView | None:
    """The agent that wrote a message, from its header: a child's report
    names the child, a child's objective its parent. Any other step names
    none, and neither does a message a person or a program wrote."""
    header = step.header
    if step.type is not AgentStepType.MESSAGE or not isinstance(header, InputHeader):
        return None
    if header.agent is None:
        return None
    return AgentRefView(kind=header.agent.kind, agent_session_id=header.agent.agent_session_id)


def usage_view(usage: Usage | None) -> AgentStepUsageView | None:
    return None if usage is None else AgentStepUsageView.model_validate(usage.model_dump())


def step_view(step: AgentStep) -> AgentStepView:
    header = step.header
    responded = header if isinstance(header, ModelResponseHeader) else None
    return AgentStepView(
        id=step.id,
        seq=step.seq,
        loop_id=step.loop_id,
        type=step.type,
        actor=step.actor,
        origin=step.origin,
        responds_to=step.responds_to,
        refs=list(step.refs),
        created_at=step.created_at,
        text=text_of(step),
        thinking=thinking_of(step),
        tool_uses=tool_uses_of(step),
        tool_use_id=tool_use_id_of(step),
        agent=agent_of(step),
        tools=[use.name for use in step.as_tool_uses()] if responded is not None else [],
        stop_reason=(
            None
            if responded is None or responded.stop_reason is None
            else StopReason(responded.stop_reason)
        ),
        usage=usage_view(responded.usage) if responded is not None else None,
        tool=header.tool if isinstance(header, ToolRequestHeader) else None,
        failure=header.failure if isinstance(header, ToolResponseHeader) else None,
        command=header.command if isinstance(header, ControlHeader) else None,
        park=park_view(header.park) if isinstance(header, ParkedHeader) else None,
        outcome=header.outcome if isinstance(header, LoopEndedHeader) else None,
        cause=header.cause if isinstance(header, LoopEndedHeader) else None,
        snapshot=snapshot_view(named_snapshot(step)),
        author=header.principal.id if isinstance(header, InputHeader) else None,
        participant=isinstance(header, InputHeader) and header.participant,
        steerer=header.steer.steerer.id
        if isinstance(header, SwitchedHeader) and header.steer
        else None,
        visibility=header.visibility.visibility
        if isinstance(header, SwitchedHeader) and header.visibility
        else None,
    )


def agent_session_usage_view(usage: AgentSessionUsage) -> AgentSessionUsageView:
    last = usage.records[-1].id if usage.records else None
    return AgentSessionUsageView.model_validate(
        {
            "agent_session_id": usage.agent_session_id,
            "items": [record.model_dump() for record in usage.records],
            "next_cursor": encode_cursor("usage", last) if usage.has_more and last else None,
            "loops": [loop.model_dump() for loop in usage.loops],
            "has_more_loops": usage.has_more_loops,
            "total": usage.total.model_dump(),
        }
    )


def snapshot_view(snapshot: AgentWorkspaceSnapshot | None) -> SnapshotView | None:
    return None if snapshot is None else SnapshotView.model_validate(snapshot.model_dump())


class AgentSessionsServiceImpl(AgentSessionsServiceInterface):
    def __init__(
        self,
        sessions: AgentSessionsManagerInterface,
        agents: AgentsManagerInterface,
        steps: AgentStepsManagerInterface,
        tools: ToolsManagerInterface,
        attribution: AttributionManagerInterface,
        loop: LoopManagerInterface,
        windows: WindowsManagerInterface,
        spend_budgets_operator: SpendBudgetsOperatorManagerInterface,
        agent_projects: AgentProjectsManagerInterface,
        *,
        agent_project_required: bool,
        kinds: AgentKindCatalog,
    ) -> None:
        """`agent_project_required` refuses a session started in no agent project: what
        every stack but a local one sets, so no per-agent-project policy is
        skipped by a session that names none."""
        self._windows = windows
        self._sessions = sessions
        self._agents = agents
        self._steps = steps
        self._tools = tools
        self._attribution = attribution
        self._loop = loop
        self._spend_budgets_operator = spend_budgets_operator
        self._agent_projects = agent_projects
        self._project_required = agent_project_required
        self._kinds = kinds

    async def _viewed(self, ctx: TenantContext, session: AgentSession) -> AgentSessionView:
        (opened,) = await self._sessions.open_titles(ctx, [session])
        return agent_session_view(opened)

    async def _paged(
        self, ctx: TenantContext, page: AgentSessionPage, listed: str
    ) -> AgentSessionPageView:
        """A page as the API lists it: its titles opened at once, a call to
        the key service for the page, whatever its size."""
        opened = await self._sessions.open_titles(ctx, page.items)
        return session_page(page.model_copy(update={"items": tuple(opened)}), listed)

    async def start_agent_session(
        self, ctx: TenantContext, body: StartAgentSessionRequest, agent_session_id: UUID
    ) -> AgentSessionView:
        start = Start(id=agent_session_id, kind=body.kind, title=body.title)
        if body.agent_project_id is not None:
            return await self._viewed(
                ctx,
                await self._agent_projects.start_agent_session(ctx, body.agent_project_id, start),
            )
        if self._project_required:
            raise ValidationFailed(
                "a session starts in an agent project: name its agent_project_id"
            )
        return await self._viewed(ctx, await self._agents.start_agent_session(ctx, start))

    async def get_agent_session(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSessionView:
        return await self._viewed(
            ctx, await self._sessions.get_agent_session(ctx, agent_session_id)
        )

    async def list_agent_sessions(
        self,
        ctx: TenantContext,
        among: Among,
        status: AgentSessionStatus | None,
        cursor: str | None,
        limit: int,
    ) -> AgentSessionPageView:
        after = decode_cursor(SESSIONS, cursor) if cursor else None
        page = await self._sessions.get_agent_sessions(
            ctx, status, after, clamp_limit(limit), among
        )
        return await self._paged(ctx, page, SESSIONS)

    async def get_children(
        self, ctx: TenantContext, agent_session_id: UUID, cursor: str | None, limit: int
    ) -> AgentSessionPageView:
        after = decode_cursor(CHILDREN, cursor) if cursor else None
        await self._sessions.get_agent_session(ctx, agent_session_id)
        page = await self._sessions.get_children(ctx, agent_session_id, after, clamp_limit(limit))
        # A deleted child is on no read until it is restored. The manager
        # answers it, since a tree's walk passes through it, so it is left
        # out here; the cursor still follows the page as read.
        listed = await self._paged(ctx, page, CHILDREN)
        return AgentSessionPageView(
            items=[child for child in listed.items if child.deleted_at is None],
            next_cursor=listed.next_cursor,
        )

    async def archive_agent_session(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSessionView:
        return agent_session_view(await self._sessions.archive_agent_session(ctx, agent_session_id))

    async def delete_agent_session(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSessionView:
        return agent_session_view(await self._sessions.delete_agent_session(ctx, agent_session_id))

    async def restore_agent_session(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSessionView:
        return agent_session_view(await self._sessions.restore_agent_session(ctx, agent_session_id))

    async def add_participant(
        self, ctx: TenantContext, agent_session_id: UUID, user_id: UUID
    ) -> AgentSessionView:
        return await self._viewed(
            ctx, await self._sessions.add_participant(ctx, agent_session_id, user_id)
        )

    async def remove_participant(
        self, ctx: TenantContext, agent_session_id: UUID, user_id: UUID
    ) -> AgentSessionView:
        return await self._viewed(
            ctx, await self._sessions.remove_participant(ctx, agent_session_id, user_id)
        )

    async def switch_visibility(
        self, ctx: TenantContext, agent_session_id: UUID, body: VisibilityRequest
    ) -> AgentSessionView:
        switched = await self._sessions.switch_visibility(ctx, agent_session_id, body.visibility)
        return await self._viewed(ctx, switched)

    async def send_message(
        self, ctx: TenantContext, agent_session_id: UUID, body: MessageRequest, agent_step_id: UUID
    ) -> AgentStepView:
        message = message_step(agent_step_id, utcnow(), agent_session_id, ctx, body.text)
        (stored,), _ = await self._sessions.receive(ctx, agent_session_id, [message])
        return step_view(stored)

    async def send_control(
        self, ctx: TenantContext, agent_session_id: UUID, body: ControlRequest, agent_step_id: UUID
    ) -> AgentStepView:
        command = ControlCommand(body.command.value)
        call = None
        if body.request_seq is not None:
            call = (await self._tool_request(ctx, agent_session_id, body.request_seq)).id
        snapshot = None
        if body.snapshot_id is not None:
            # Read after the session itself, so another tenant's names
            # nothing, and found in this session's history alone, so no
            # session starts from another's snapshot.
            await self._sessions.get_agent_session(ctx, agent_session_id)
            snapshot = await self._tools.find_snapshot(ctx, agent_session_id, body.snapshot_id)
        control = control_step(
            agent_step_id, utcnow(), agent_session_id, ctx, command, call, snapshot
        )
        (stored,), _ = await self._sessions.receive(ctx, agent_session_id, [control])
        return step_view(stored)

    async def _tool_request(
        self, ctx: TenantContext, agent_session_id: UUID, seq: int
    ) -> AgentStep:
        """The tool request at `seq` in the session's history, read after the
        session itself, so another tenant's names nothing; `NotFound` when no
        tool request is there."""
        await self._sessions.get_agent_session(ctx, agent_session_id)
        page = await self._steps.get_agent_steps(ctx, agent_session_id, seq - 1, 1)
        found = next((step for step in page.items if step.seq == seq), None)
        if found is None or found.type is not AgentStepType.TOOL_REQUEST:
            raise NotFound(f"no tool request at {seq} in agent session {agent_session_id}")
        return found

    async def decide_call(
        self, ctx: TenantContext, agent_session_id: UUID, request_seq: int, body: DecisionRequest
    ) -> AgentStepView:
        # The session first: one another tenant holds, or one marked
        # deleted, takes no decision.
        await self._sessions.get_agent_session(ctx, agent_session_id)
        decided = await self._tools.decide_call(
            ctx, agent_session_id, request_seq, approve=body.approve, note=body.note
        )
        await self._sessions.project_status(ctx, agent_session_id)
        return step_view(decided)

    async def set_deadline(
        self, ctx: TenantContext, agent_session_id: UUID, body: DeadlineRequest
    ) -> AgentSessionView:
        await self._agents.set_deadline(ctx, agent_session_id, body.deadline)
        return await self._viewed(
            ctx, await self._sessions.get_agent_session(ctx, agent_session_id)
        )

    async def assign_principal(
        self, ctx: TenantContext, agent_session_id: UUID, body: PrincipalRequest | None
    ) -> AgentSessionView:
        steerer = None if body is None else body.steerer
        await self._attribution.assign_principal(ctx, agent_session_id, steerer)
        return await self._viewed(
            ctx, await self._sessions.get_agent_session(ctx, agent_session_id)
        )

    async def take_over(self, ctx: TenantContext, agent_session_id: UUID) -> AgentSessionView:
        return await self._viewed(ctx, await self._loop.take_over(ctx, agent_session_id))

    async def give_back(
        self, ctx: TenantContext, agent_session_id: UUID, body: GiveBackRequest
    ) -> AgentSessionView:
        return await self._viewed(
            ctx, await self._loop.give_back(ctx, agent_session_id, body.summary)
        )

    async def complete_job(
        self, ctx: TenantContext, agent_session_id: UUID, key: UUID, body: JobCompletionRequest
    ) -> AgentSessionView:
        completion = JobCompletion(
            key=key, handle=body.handle, text=body.text, failure=body.failure
        )
        return await self._viewed(
            ctx, await self._loop.complete_job(ctx, agent_session_id, completion)
        )

    async def get_agent_steps(
        self, ctx: TenantContext, agent_session_id: UUID, after_seq: int, limit: int
    ) -> AgentStepPageView:
        await self._sessions.get_agent_session(ctx, agent_session_id)
        page = await self._steps.get_agent_steps(
            ctx, agent_session_id, after_seq, clamp_limit(limit)
        )
        return AgentStepPageView(
            items=[step_view(step) for step in page.items], has_more=page.has_more
        )

    async def get_tool_output(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        tool_output_id: UUID,
        start: int,
        limit: int,
    ) -> ToolOutputPageView:
        # The session first, so one marked deleted keeps its tool outputs closed
        # as it keeps its history.
        await self._sessions.get_agent_session(ctx, agent_session_id)
        page = await self._windows.get_tool_output(
            ctx, agent_session_id, tool_output_id, start, limit
        )
        return ToolOutputPageView(
            tool_output_id=page.tool_output_id,
            start=page.offset,
            text=page.text,
            characters=page.characters,
            has_more=page.has_more,
        )

    async def get_questions(self, ctx: TenantContext, agent_session_id: UUID) -> list[QuestionView]:
        session = await self._sessions.get_agent_session(ctx, agent_session_id)
        if session.park is None:
            return []
        return questions_of(session, await self._history(ctx, agent_session_id))

    async def get_approvals(self, ctx: TenantContext, agent_session_id: UUID) -> list[ApprovalView]:
        session = await self._sessions.get_agent_session(ctx, agent_session_id)
        if not waits_on_approval(session.park):
            return []
        return approvals_of(session, await self._history(ctx, agent_session_id))

    async def get_org_approvals(
        self, ctx: TenantContext, cursor: str | None, limit: int
    ) -> ApprovalPageView:
        after = decode_cursor(APPROVALS, cursor) if cursor else None
        # A sub-agent holds its calls under a root in any status, an idle one
        # included: each root the person sees is read with its whole tree.
        page = await self._sessions.get_agent_sessions(ctx, None, after, clamp_limit(limit))
        held: list[ApprovalView] = []
        for root in page.items:
            for session in await self._tree(ctx, root):
                # A sub-agent marked deleted is on no list, as a root is not.
                if session.deleted_at is None and waits_on_approval(session.park):
                    held += approvals_of(session, await self._history(ctx, session.id))
        last = page.items[-1].id if page.items and page.has_more else None
        return ApprovalPageView(
            items=held, next_cursor=None if last is None else encode_cursor(APPROVALS, last)
        )

    async def _tree(self, ctx: TenantContext, root: AgentSession) -> list[AgentSession]:
        """A root and every sub-agent under it, each parent before its
        children, read through the engine's children of each parent, which
        answers only for a parent the person sees."""
        tree = [root]
        index = 0
        while index < len(tree):
            parent = tree[index]
            index += 1
            after: UUID | None = None
            while True:
                page = await self._sessions.get_children(ctx, parent.id, after, LIMIT_MAX)
                tree.extend(page.items)
                if not page.has_more or not page.items:
                    break
                after = page.items[-1].id
        return tree

    async def get_bounds(self, ctx: TenantContext, agent_session_id: UUID) -> BoundsView:
        session = await self._sessions.get_agent_session(ctx, agent_session_id)
        kind = self._kinds.get(session.kind, session.kind_version)
        return bounds_of(kind, await self._agents.tree_of(ctx, agent_session_id))

    async def get_tool_calls(
        self, ctx: TenantContext, agent_session_id: UUID, after_seq: int, limit: int
    ) -> ToolCallPageView:
        await self._sessions.get_agent_session(ctx, agent_session_id)
        calls = [
            call
            for call in tool_calls_of(await self._history(ctx, agent_session_id), utcnow())
            if call.seq > after_seq
        ]
        bounded = clamp_limit(limit)
        return ToolCallPageView(items=calls[:bounded], has_more=len(calls) > bounded)

    async def get_usage(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSessionModelUsageView:
        await self._sessions.get_agent_session(ctx, agent_session_id)
        return usage_of(await self._history(ctx, agent_session_id))

    async def _history(self, ctx: TenantContext, agent_session_id: UUID) -> list[AgentStep]:
        """The session's whole history, in order, a page at a time. Read
        after the session itself, so another tenant's is never reached."""
        steps: list[AgentStep] = []
        while True:
            after = steps[-1].seq if steps else 0
            page = await self._steps.get_agent_steps(ctx, agent_session_id, after, HISTORY_PAGE)
            steps.extend(page.items)
            if not page.has_more or not page.items:
                return steps

    async def get_agent_session_usage(
        self,
        admin: OperatorContext,
        org_id: UUID,
        agent_session_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> AgentSessionUsageView:
        after = decode_cursor("usage", cursor) if cursor else None
        usage = await self._spend_budgets_operator.get_agent_session_usage(
            admin, org_id, agent_session_id, after, clamp_limit(limit)
        )
        return agent_session_usage_view(usage)
