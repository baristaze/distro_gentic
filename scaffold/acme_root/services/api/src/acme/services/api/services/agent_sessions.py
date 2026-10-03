"""The agent sessions service: what the wire can do with a session, in
views. A session is started, spoken to, steered, and read; its loop runs in
the session runner, never here."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.context import TenantContext
from acme.services.api.types.agent_sessions import (
    AgentSessionPageView,
    AgentSessionView,
    ControlRequest,
    DecisionRequest,
    MessageRequest,
    StartSessionRequest,
    StepPageView,
    StepView,
)


class AgentSessionsServiceInterface(ABC):
    @abstractmethod
    async def start_session(
        self, ctx: TenantContext, body: StartSessionRequest, session_id: UUID
    ) -> AgentSessionView:
        """A session on the latest version of the kind, idle, under
        `session_id`, the id the idempotency record minted. A kind the
        product does not run is refused."""
        ...

    @abstractmethod
    async def get_session(self, ctx: TenantContext, session_id: UUID) -> AgentSessionView: ...

    @abstractmethod
    async def get_sessions(
        self, ctx: TenantContext, status: SessionStatus | None, cursor: str | None, limit: int
    ) -> AgentSessionPageView:
        """One page of the tenant's sessions in a status, or in any, by id;
        a deleted session is on no page."""
        ...

    @abstractmethod
    async def get_children(
        self, ctx: TenantContext, session_id: UUID, cursor: str | None, limit: int
    ) -> AgentSessionPageView:
        """One page of the sessions `session_id` spawned, by id; the parent
        is read first, so another tenant's names nothing."""
        ...

    @abstractmethod
    async def archive_session(self, ctx: TenantContext, session_id: UUID) -> AgentSessionView:
        """The archive flag set on an idle session; a person's message
        clears it. One with a loop open is refused."""
        ...

    @abstractmethod
    async def delete_session(self, ctx: TenantContext, session_id: UUID) -> AgentSessionView:
        """The session marked deleted: hidden from every read until it is
        restored or its retention ends. One with a loop open is refused."""
        ...

    @abstractmethod
    async def restore_session(self, ctx: TenantContext, session_id: UUID) -> AgentSessionView:
        """A deleted session back as it was, with its history; one past its
        retention is `NotFound`."""
        ...

    @abstractmethod
    async def send_message(
        self, ctx: TenantContext, session_id: UUID, body: MessageRequest, step_id: UUID
    ) -> StepView:
        """The message, durable when this answers, under `step_id`; the
        session's status follows it, and an idle session wakes."""
        ...

    @abstractmethod
    async def send_control(
        self, ctx: TenantContext, session_id: UUID, body: ControlRequest, step_id: UUID
    ) -> StepView:
        """The control, durable when this answers, under `step_id`; a run
        reads it between steps and while a tool runs. An interrupt names the
        tool request it stops by its seq: `NotFound` when none is there."""
        ...

    @abstractmethod
    async def decide_call(
        self, ctx: TenantContext, session_id: UUID, request_seq: int, body: DecisionRequest
    ) -> StepView:
        """A person's decision on the tool request at `request_seq`, bound to
        its tool and its input; the session's status follows it."""
        ...

    @abstractmethod
    async def get_steps(
        self, ctx: TenantContext, session_id: UUID, after_seq: int, limit: int
    ) -> StepPageView: ...
