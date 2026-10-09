"""The wire types of agent sessions: a session, one step of its history,
and what a person sends it. A step's view is flat: what it is, who wrote
it, what it says as text, and the few fields of its header a reader acts
on. Its content is the session's, so a reader of the org reads it as the
session's own reader does."""

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from acme.integrations.model_providers.types import StopReason
from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.agents.types.request import MAX_TITLE
from acme.om.attribution.types.principal import MAX_KIND
from acme.om.steps.types.header import ControlCommand, LoopOutcome, ParkReason, ToolFailure
from acme.om.steps.types.step import Actor, Origin, StepType
from acme.om.tools.types.call import Verdict
from acme.services.api.types.common import RequestBody, View

MAX_MESSAGE = 100_000
"""The most characters one message carries."""


class LineParkView(View):
    """The line a loop waits in: the request, what it asked for (a kind,
    and the resource when it named one), its place (1 is next in some line
    it stands in), and the estimate of its wait."""

    request_id: UUID
    kind: str
    resource_id: UUID | None
    place: int | None
    estimate_seconds: float | None


class ParkView(View):
    """Why a parked loop waits, what clears it, and when it tries again by
    itself; a park only a person clears has no time, and neither has a park
    in line, which names where it stands."""

    reason: ParkReason
    unlock: str
    retry_at: datetime | None
    line: LineParkView | None = None


class AgentSessionView(View):
    """A session: its kind, its title, and its status, which follows its
    steps. `pending` while an input waits for a run, `running` while a run
    holds its loop, `parked` while the loop waits, `idle` when no loop is
    open. A sub-agent names the session that spawned it, and every session
    the root of its tree. `deleted_at` is set only on the answer to a
    delete: a deleted session is on no read until it is restored."""

    id: UUID
    title: str
    kind: str
    kind_version: int
    status: SessionStatus
    park: ParkView | None
    parent_id: UUID | None
    root_id: UUID
    created_at: datetime
    created_by: UUID
    archived_at: datetime | None
    deleted_at: datetime | None


class AgentSessionPageView(View):
    """One page of sessions, by id. `next_cursor` fetches the next page and
    is null on the last one."""

    items: list[AgentSessionView]
    next_cursor: str | None


class StepUsageView(View):
    """What a model call used, as its provider reported it, in disjoint
    classes, so no token is counted twice."""

    input: int
    cache_read: int
    cache_write: int
    output: int
    thinking: int


MAX_SHOWN = 4_096
"""The most characters one string of a tool use's input carries in a
step's view; a longer one is cut there and ends in an ellipsis."""


class ToolUseView(View):
    """One call a model response made: its id, which the call's request and
    response name, the tool, and what the tool was asked, each string cut
    at `MAX_SHOWN`."""

    id: str
    name: str
    input: dict[str, JsonValue]


class AgentRefView(View):
    """The agent that wrote a message: its kind and the session it runs in.
    The session is one of the same tree, which a reader of this session
    reads too: a sub-agent's report names the child, a child's objective
    its parent."""

    kind: str
    session_id: UUID


class StepView(View):
    """One step of a session's history, in its order. `text` is what it
    says: a message's words, a model's answer, a tool's result. A model
    response also says what it thought (`thinking`) and the calls it made
    (`tool_uses`); a tool response names the call it answers
    (`tool_use_id`). Each of these is the step's content: where it is gone,
    its session's key revoked or its content never kept here, each is empty
    as `text` is. The rest is its header's, by type: the agent that wrote a
    message, on a message an agent wrote (`agent`); the tools a model
    response called, why it stopped, and what it used; a tool call's tool,
    the id of the call it runs, and the class of its failure; a control's
    command; a park; a loop's outcome."""

    id: UUID
    seq: int
    loop_id: UUID
    type: StepType
    actor: Actor
    origin: Origin
    responds_to: UUID | None
    refs: list[UUID]
    created_at: datetime
    text: str
    thinking: str
    tool_uses: list[ToolUseView]
    tool_use_id: str | None
    agent: AgentRefView | None
    tools: list[str]
    stop_reason: StopReason | None
    usage: StepUsageView | None
    tool: str | None
    failure: ToolFailure | None
    command: ControlCommand | None
    park: ParkView | None
    outcome: LoopOutcome | None


class StepPageView(View):
    """One page of a session's history, after the seq the request named.
    With `has_more`, the next page starts after the last step's seq."""

    items: list[StepView]
    has_more: bool


class QuestionView(View):
    """What a session asks of a person now: a park on a person that is no
    call's decision, such as a step guard to lift, a deadline to move, or a
    principal to name. `unlock` is what clears it, sent as a control; `seq`
    is the step that parked it."""

    session_id: UUID
    seq: int
    asked_at: datetime
    unlock: str


class ApprovalView(View):
    """A tool call held for a person's decision: its session, the seq it is
    decided at, its tool and the class of power it exercises, and the
    principal it runs under. Its input stays in the history; the request
    names only its hash."""

    session_id: UUID
    seq: int
    requested_at: datetime
    tool: str
    authorization_class: str
    principal_id: UUID


class ApprovalPageView(View):
    """The calls held across one page of the tenant's parked sessions, by
    session id. `next_cursor` reads the next page of sessions and is null
    on the last one; a page may hold no call and still have a next."""

    items: list[ApprovalView]
    next_cursor: str | None


class LoopLimitsView(View):
    """The bounds of one loop of the session's kind: the model calls before
    the step guard parks it for a person, the tool errors or identical
    calls in a row that end it, the nudges it gives, and how long one run
    drives it before handing it on."""

    step_guard: int
    error_streak: int
    nudges: int
    run_time_seconds: float


class TreeBoundsView(View):
    """What the session's tree shares: how deep and how many sub-agents it
    may have, how many run at once, the one deadline, and how many were
    spawned so far."""

    root_id: UUID
    height: int
    count: int
    concurrency: int | None
    deadline: datetime | None
    size: int


class BoundsView(View):
    """The bounds a session runs under: its kind's loop limits, the deadline
    its kind gives a tree it roots, and its tree's record."""

    kind: str
    kind_version: int
    loop: LoopLimitsView
    kind_deadline_seconds: float | None
    tree: TreeBoundsView


class ToolCallView(View):
    """One tool call of a session: its request, a person's decision on it
    when one was asked, and its response once it answered. A call with no
    response is open: held for a decision, or running."""

    seq: int
    loop_id: UUID
    requested_at: datetime
    tool: str
    authorization_class: str
    principal_id: UUID
    decision: Verdict | None
    decided_by: UUID | None
    response_seq: int | None
    responded_at: datetime | None
    failure: ToolFailure | None


class ToolCallPageView(View):
    """One page of a session's tool calls, in order, after the seq the
    request named. With `has_more`, the next page starts after the last
    call's seq."""

    items: list[ToolCallView]
    has_more: bool


class FillUsageView(View):
    """What one model, at its provider, used in the session's calls: the
    calls that answered, and their tokens by class, no token counted
    twice."""

    fill: str
    calls: int
    input: int
    cache_read: int
    cache_write: int
    output: int
    thinking: int


class SessionModelUsageView(View):
    """What a session's model calls used, as each provider reported it, per
    model and in total."""

    calls: int
    input: int
    cache_read: int
    cache_write: int
    output: int
    thinking: int
    fills: list[FillUsageView]


class StartSessionRequest(RequestBody):
    """A session to start on the latest version of a kind the product runs,
    in a project of the caller's tenant. Outside a local stack a session
    starts in a project or not at all."""

    kind: str = Field(min_length=1, max_length=MAX_KIND)
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    project_id: UUID | None = None


class MessageRequest(RequestBody):
    """A message to the session, said in the caller's name. It wakes an idle
    session, and a running loop reads it at its next model request."""

    text: str = Field(min_length=1, max_length=MAX_MESSAGE)


class SessionControl(StrEnum):
    """The controls a person sends a session out of band. A decision on one
    tool call is a route of its own."""

    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    INTERRUPT = "interrupt"
    COMPACT = "compact"
    UNLOCK = "unlock"


class ControlRequest(RequestBody):
    """A control. An interrupt names the seq of the tool request it stops,
    and no other control names one."""

    command: SessionControl
    request_seq: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _an_interrupt_names_its_call(self) -> Self:
        if (self.command is SessionControl.INTERRUPT) != (self.request_seq is not None):
            raise ValueError("an interrupt names the call it stops, and no other control names one")
        return self


class DecisionRequest(RequestBody):
    """A person's decision on the tool call at a seq. A denial's note is what
    the model reads."""

    approve: bool
    note: str = Field(default="", max_length=MAX_MESSAGE)
