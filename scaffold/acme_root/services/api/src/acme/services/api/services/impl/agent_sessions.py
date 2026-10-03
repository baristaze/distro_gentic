from uuid import UUID

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import (
    AgentSession,
    AgentSessionPage,
    SessionStatus,
)
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.request import Start
from acme.om.base import utcnow
from acme.om.context import TenantContext
from acme.om.exceptions import NotFound, ValidationFailed
from acme.om.projects import ProjectsManagerInterface
from acme.om.steps import StepsManagerInterface
from acme.om.steps.rules import control_step, message_step
from acme.om.steps.types.content import TextBlock
from acme.om.steps.types.header import (
    ControlCommand,
    ControlHeader,
    LoopEndedHeader,
    ModelResponseHeader,
    Park,
    ParkedHeader,
    ToolRequestHeader,
    ToolResponseHeader,
)
from acme.om.steps.types.step import Step, StepType
from acme.om.tools import ToolsManagerInterface
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
    AgentSessionPageView,
    AgentSessionView,
    ApprovalPageView,
    ApprovalView,
    BoundsView,
    ControlRequest,
    DecisionRequest,
    MessageRequest,
    ParkView,
    QuestionView,
    SessionUsageView,
    StartSessionRequest,
    StepPageView,
    StepView,
    ToolCallPageView,
)
from acme.services.api.types.common import LIMIT_MAX, clamp_limit


def park_view(park: Park | None) -> ParkView | None:
    return None if park is None else ParkView.model_validate(park)


def session_view(session: AgentSession) -> AgentSessionView:
    return AgentSessionView(
        id=session.id,
        title=session.title,
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
        items=[session_view(session) for session in page.items],
        next_cursor=None if last is None else encode_cursor(listed, last),
    )


def text_of(step: Step) -> str:
    """What a step says: a tool response's text parts, any other step's
    text blocks. A step whose content is gone, its session's key revoked,
    says nothing: a hole in a known place, whose shape alone stays."""
    if not step.content.is_plain():
        return ""
    if step.type is StepType.TOOL_RESPONSE:
        parts = step.as_tool_response().parts
        return "\n".join(part.text for part in parts if isinstance(part, TextBlock))
    return step.as_text()


def step_view(step: Step) -> StepView:
    header = step.header
    responded = header if isinstance(header, ModelResponseHeader) else None
    return StepView(
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
        tools=[use.name for use in step.as_tool_uses()] if responded is not None else [],
        stop_reason=None if responded is None else responded.stop_reason,
        tool=header.tool if isinstance(header, ToolRequestHeader) else None,
        failure=header.failure if isinstance(header, ToolResponseHeader) else None,
        command=header.command if isinstance(header, ControlHeader) else None,
        park=park_view(header.park) if isinstance(header, ParkedHeader) else None,
        outcome=header.outcome if isinstance(header, LoopEndedHeader) else None,
    )


class AgentSessionsServiceImpl(AgentSessionsServiceInterface):
    def __init__(
        self,
        sessions: AgentSessionsManagerInterface,
        agents: AgentsManagerInterface,
        steps: StepsManagerInterface,
        tools: ToolsManagerInterface,
        projects: ProjectsManagerInterface,
        *,
        project_required: bool,
    ) -> None:
        """`project_required` refuses a session started in no project: what
        every stack but a local one sets, so no per-project policy is
        skipped by a session that names none."""
        self._sessions = sessions
        self._agents = agents
        self._steps = steps
        self._tools = tools
        self._projects = projects
        self._project_required = project_required

    async def start_session(
        self, ctx: TenantContext, body: StartSessionRequest, session_id: UUID
    ) -> AgentSessionView:
        start = Start(id=session_id, kind=body.kind, title=body.title)
        if body.project_id is not None:
            return session_view(await self._projects.start_session(ctx, body.project_id, start))
        if self._project_required:
            raise ValidationFailed("a session starts in a project: name its project_id")
        return session_view(await self._agents.start_session(ctx, start))

    async def get_session(self, ctx: TenantContext, session_id: UUID) -> AgentSessionView:
        return session_view(await self._sessions.get_session(ctx, session_id))

    async def get_sessions(
        self, ctx: TenantContext, status: SessionStatus | None, cursor: str | None, limit: int
    ) -> AgentSessionPageView:
        after = decode_cursor(SESSIONS, cursor) if cursor else None
        page = await self._sessions.get_sessions(ctx, status, after, clamp_limit(limit))
        return session_page(page, SESSIONS)

    async def get_children(
        self, ctx: TenantContext, session_id: UUID, cursor: str | None, limit: int
    ) -> AgentSessionPageView:
        after = decode_cursor(CHILDREN, cursor) if cursor else None
        await self._sessions.get_session(ctx, session_id)
        page = await self._sessions.get_children(ctx, session_id, after, clamp_limit(limit))
        # A deleted child is on no read until it is restored. The manager
        # answers it, since a tree's walk passes through it, so it is left
        # out here; the cursor still follows the page as read.
        listed = session_page(page, CHILDREN)
        return AgentSessionPageView(
            items=[child for child in listed.items if child.deleted_at is None],
            next_cursor=listed.next_cursor,
        )

    async def archive_session(self, ctx: TenantContext, session_id: UUID) -> AgentSessionView:
        return session_view(await self._sessions.archive_session(ctx, session_id))

    async def delete_session(self, ctx: TenantContext, session_id: UUID) -> AgentSessionView:
        return session_view(await self._sessions.delete_session(ctx, session_id))

    async def restore_session(self, ctx: TenantContext, session_id: UUID) -> AgentSessionView:
        return session_view(await self._sessions.restore_session(ctx, session_id))

    async def send_message(
        self, ctx: TenantContext, session_id: UUID, body: MessageRequest, step_id: UUID
    ) -> StepView:
        message = message_step(step_id, utcnow(), session_id, ctx, body.text)
        (stored,), _ = await self._sessions.receive(ctx, session_id, [message])
        return step_view(stored)

    async def send_control(
        self, ctx: TenantContext, session_id: UUID, body: ControlRequest, step_id: UUID
    ) -> StepView:
        command = ControlCommand(body.command.value)
        call = None
        if body.request_seq is not None:
            call = (await self._tool_request(ctx, session_id, body.request_seq)).id
        control = control_step(step_id, utcnow(), session_id, ctx, command, call)
        (stored,), _ = await self._sessions.receive(ctx, session_id, [control])
        return step_view(stored)

    async def _tool_request(self, ctx: TenantContext, session_id: UUID, seq: int) -> Step:
        """The tool request at `seq` in the session's history, read after the
        session itself, so another tenant's names nothing; `NotFound` when no
        tool request is there."""
        await self._sessions.get_session(ctx, session_id)
        page = await self._steps.get_steps(ctx, session_id, seq - 1, 1)
        found = next((step for step in page.items if step.seq == seq), None)
        if found is None or found.type is not StepType.TOOL_REQUEST:
            raise NotFound(f"no tool request at {seq} in agent session {session_id}")
        return found

    async def decide_call(
        self, ctx: TenantContext, session_id: UUID, request_seq: int, body: DecisionRequest
    ) -> StepView:
        # The session first: one another tenant holds, or one marked
        # deleted, takes no decision.
        await self._sessions.get_session(ctx, session_id)
        decided = await self._tools.decide_call(
            ctx, session_id, request_seq, approve=body.approve, note=body.note
        )
        await self._sessions.project_status(ctx, session_id)
        return step_view(decided)

    async def get_steps(
        self, ctx: TenantContext, session_id: UUID, after_seq: int, limit: int
    ) -> StepPageView:
        await self._sessions.get_session(ctx, session_id)
        page = await self._steps.get_steps(ctx, session_id, after_seq, clamp_limit(limit))
        return StepPageView(items=[step_view(step) for step in page.items], has_more=page.has_more)

    async def get_questions(self, ctx: TenantContext, session_id: UUID) -> list[QuestionView]:
        session = await self._sessions.get_session(ctx, session_id)
        if session.park is None:
            return []
        return questions_of(session, await self._history(ctx, session_id))

    async def get_approvals(self, ctx: TenantContext, session_id: UUID) -> list[ApprovalView]:
        session = await self._sessions.get_session(ctx, session_id)
        if not waits_on_approval(session.park):
            return []
        return approvals_of(session, await self._history(ctx, session_id))

    async def get_org_approvals(
        self, ctx: TenantContext, cursor: str | None, limit: int
    ) -> ApprovalPageView:
        after = decode_cursor(APPROVALS, cursor) if cursor else None
        page = await self._sessions.get_sessions(
            ctx, SessionStatus.PARKED, after, clamp_limit(limit)
        )
        held: list[ApprovalView] = []
        for session in page.items:
            if waits_on_approval(session.park):
                held += approvals_of(session, await self._history(ctx, session.id))
        last = page.items[-1].id if page.items and page.has_more else None
        return ApprovalPageView(
            items=held, next_cursor=None if last is None else encode_cursor(APPROVALS, last)
        )

    async def get_bounds(self, ctx: TenantContext, session_id: UUID) -> BoundsView:
        kind = await self._agents.kind_of(ctx, session_id)
        return bounds_of(kind, await self._agents.tree_of(ctx, session_id))

    async def get_tool_calls(
        self, ctx: TenantContext, session_id: UUID, after_seq: int, limit: int
    ) -> ToolCallPageView:
        await self._sessions.get_session(ctx, session_id)
        calls = [
            call
            for call in tool_calls_of(await self._history(ctx, session_id), utcnow())
            if call.seq > after_seq
        ]
        bounded = clamp_limit(limit)
        return ToolCallPageView(items=calls[:bounded], has_more=len(calls) > bounded)

    async def get_usage(self, ctx: TenantContext, session_id: UUID) -> SessionUsageView:
        await self._sessions.get_session(ctx, session_id)
        return usage_of(await self._history(ctx, session_id))

    async def _history(self, ctx: TenantContext, session_id: UUID) -> list[Step]:
        """The session's whole history, in order, a page at a time. Read
        after the session itself, so another tenant's is never reached."""
        steps: list[Step] = []
        while True:
            after = steps[-1].seq if steps else 0
            page = await self._steps.get_steps(ctx, session_id, after, HISTORY_PAGE)
            steps.extend(page.items)
            if not page.has_more or not page.items:
                return steps
