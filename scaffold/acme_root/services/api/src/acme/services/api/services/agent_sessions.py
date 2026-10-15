"""The agent sessions service: what the wire can do with a session, in
views. A session is started, listed, joined, spoken to, steered, and read;
its loop runs in the session runner, never here. Each one is read as the
person sees it: one not visible to them answers as one that never
existed."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_sessions.types.agent_session import AgentSessionStatus, Among
from acme.om.context import OperatorContext, TenantContext
from acme.services.api.types.agent_sessions import (
    AgentSessionModelUsageView,
    AgentSessionPageView,
    AgentSessionUsageView,
    AgentSessionView,
    AgentStepPageView,
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
    PrincipalRequest,
    QuestionView,
    StartAgentSessionRequest,
    ToolCallPageView,
    ToolOutputPageView,
    VisibilityRequest,
)


class AgentSessionsServiceInterface(ABC):
    @abstractmethod
    async def start_agent_session(
        self, ctx: TenantContext, body: StartAgentSessionRequest, agent_session_id: UUID
    ) -> AgentSessionView:
        """A session on the latest version of the kind, idle, under
        `agent_session_id`, the id the idempotency record minted. A kind the
        product does not run is refused."""
        ...

    @abstractmethod
    async def get_agent_session(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSessionView: ...

    @abstractmethod
    async def list_agent_sessions(
        self,
        ctx: TenantContext,
        among: Among,
        status: AgentSessionStatus | None,
        cursor: str | None,
        limit: int,
    ) -> AgentSessionPageView:
        """One page of the org's root sessions in a status, or in any, newest
        first: the ones the caller made or takes part in, or every one they
        see; a deleted session is on no page."""
        ...

    @abstractmethod
    async def get_children(
        self, ctx: TenantContext, agent_session_id: UUID, cursor: str | None, limit: int
    ) -> AgentSessionPageView:
        """One page of the sessions `agent_session_id` spawned, by id; the parent
        is read first, so another tenant's names nothing."""
        ...

    @abstractmethod
    async def archive_agent_session(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSessionView:
        """The archive flag set on an idle session; a person's message
        clears it. One with a loop open is refused."""
        ...

    @abstractmethod
    async def delete_agent_session(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSessionView:
        """The session marked deleted: hidden from every read until it is
        restored or its retention ends. One with a loop open is refused."""
        ...

    @abstractmethod
    async def restore_agent_session(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSessionView:
        """A deleted session back as it was, with its history; one past its
        retention is `NotFound`."""
        ...

    @abstractmethod
    async def add_participant(
        self, ctx: TenantContext, agent_session_id: UUID, user_id: UUID
    ) -> AgentSessionView:
        """`user_id` takes part in the session: the caller joining an
        org-wide one, or anyone its creator adds."""
        ...

    @abstractmethod
    async def remove_participant(
        self, ctx: TenantContext, agent_session_id: UUID, user_id: UUID
    ) -> AgentSessionView:
        """`user_id` takes no part in the session: its creator removing
        them, or they leaving on their own, never while they steer it."""
        ...

    @abstractmethod
    async def switch_visibility(
        self, ctx: TenantContext, agent_session_id: UUID, body: VisibilityRequest
    ) -> AgentSessionView:
        """Its creator switches who sees the session, recorded as a step."""
        ...

    @abstractmethod
    async def send_message(
        self, ctx: TenantContext, agent_session_id: UUID, body: MessageRequest, agent_step_id: UUID
    ) -> AgentStepView:
        """The message, durable when this answers, under `agent_step_id`; the
        session's status follows it, and an idle session wakes."""
        ...

    @abstractmethod
    async def send_control(
        self, ctx: TenantContext, agent_session_id: UUID, body: ControlRequest, agent_step_id: UUID
    ) -> AgentStepView:
        """The control, durable when this answers, under `agent_step_id`; a run
        reads it between steps and while a tool runs. An interrupt names the
        tool request it stops by its seq: `NotFound` when none is there."""
        ...

    @abstractmethod
    async def decide_call(
        self, ctx: TenantContext, agent_session_id: UUID, request_seq: int, body: DecisionRequest
    ) -> AgentStepView:
        """A person's decision on the tool request at `request_seq`, bound to
        its tool and its input; the session's status follows it."""
        ...

    @abstractmethod
    async def set_deadline(
        self, ctx: TenantContext, agent_session_id: UUID, body: DeadlineRequest
    ) -> AgentSessionView:
        """The deadline of the session's tree, moved for every session of
        it; one past now, or none, unlocks each session parked on it. The
        session as it stands after."""
        ...

    @abstractmethod
    async def assign_principal(
        self, ctx: TenantContext, agent_session_id: UUID, body: PrincipalRequest | None
    ) -> AgentSessionView:
        """The steer moves, recorded as a step: its steerer hands it to the
        participant the body names, or with none the caller takes it, its
        steerer already or, for a steerer who lapsed, one who holds
        `manage_agent_sessions`. The steerer is the principal the session's tool
        calls run under, and a loop parked on a principal who no longer
        holds is unlocked. The session as it stands after."""
        ...

    @abstractmethod
    async def take_over(self, ctx: TenantContext, agent_session_id: UUID) -> AgentSessionView:
        """The caller, in person, takes the session's environment to work by
        hand: its loop parks on a hand-over the caller holds."""
        ...

    @abstractmethod
    async def give_back(
        self, ctx: TenantContext, agent_session_id: UUID, body: GiveBackRequest
    ) -> AgentSessionView:
        """The holder, in person, gives the environment back with what they
        did, and the loop goes on."""
        ...

    @abstractmethod
    async def complete_job(
        self, ctx: TenantContext, agent_session_id: UUID, key: UUID, body: JobCompletionRequest
    ) -> AgentSessionView:
        """A job's completion, from the system it ran on: kept only for a job
        of that key and handle the session's open loop waits on, and its
        park is unlocked; anything else is `NotFound`."""
        ...

    @abstractmethod
    async def get_agent_steps(
        self, ctx: TenantContext, agent_session_id: UUID, after_seq: int, limit: int
    ) -> AgentStepPageView: ...

    @abstractmethod
    async def get_tool_output(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        tool_output_id: UUID,
        start: int,
        limit: int,
    ) -> ToolOutputPageView:
        """A page of a tool output the session keeps, from the character at
        `start`, read as its steps are."""
        ...

    @abstractmethod
    async def get_questions(self, ctx: TenantContext, agent_session_id: UUID) -> list[QuestionView]:
        """What the session asks of a person now, other than a call's
        decision; empty when it waits on nobody."""
        ...

    @abstractmethod
    async def get_approvals(self, ctx: TenantContext, agent_session_id: UUID) -> list[ApprovalView]:
        """The calls the session holds for a person's decision."""
        ...

    @abstractmethod
    async def get_org_approvals(
        self, ctx: TenantContext, cursor: str | None, limit: int
    ) -> ApprovalPageView:
        """The calls held for a decision across one page of the root sessions
        the caller sees, newest first, in any status, each with every
        sub-agent under it: a sub-agent's held call is listed to whom its
        root is visible."""
        ...

    @abstractmethod
    async def get_bounds(self, ctx: TenantContext, agent_session_id: UUID) -> BoundsView: ...

    @abstractmethod
    async def get_tool_calls(
        self, ctx: TenantContext, agent_session_id: UUID, after_seq: int, limit: int
    ) -> ToolCallPageView:
        """The session's tool calls in order, strictly after `after_seq`."""
        ...

    @abstractmethod
    async def get_usage(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSessionModelUsageView: ...

    @abstractmethod
    async def get_agent_session_usage(
        self,
        admin: OperatorContext,
        org_id: UUID,
        agent_session_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> AgentSessionUsageView:
        """On the operator plane: a page of one session's usage records and
        its rollups; `cursor` is the previous page's `next_cursor`."""
        ...
