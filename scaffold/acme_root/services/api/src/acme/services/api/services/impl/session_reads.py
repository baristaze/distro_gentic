"""What a session's history says, projected for a reader: the question it
asks of a person, the calls it holds for a decision, every tool call with
its decision and its answer, and what its model calls used. Pure: a
session and its steps in, views out. Each reads the steps' headers, never
their content, so a session whose key is revoked reads the same."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents.loop_rules import APPROVAL_UNLOCK
from acme.om.agents.types.kind import AgentKind
from acme.om.agents.types.tree import AgentTree
from acme.om.notifications.rules import held_calls, needs_person, parked_step
from acme.om.steps.types.header import (
    ControlCommand,
    ControlHeader,
    ModelRequestHeader,
    ModelResponseHeader,
    Park,
    ParkReason,
    ToolRequestHeader,
    ToolResponseHeader,
)
from acme.om.steps.types.step import Step, StepType
from acme.om.tools.types.call import Verdict
from acme.services.api.types.agent_sessions import (
    ApprovalView,
    BoundsView,
    FillUsageView,
    LoopLimitsView,
    QuestionView,
    SessionModelUsageView,
    ToolCallView,
    TreeBoundsView,
)


def waits_on_approval(park: Park | None) -> bool:
    return park is not None and park.reason is ParkReason.PERSON and park.unlock == APPROVAL_UNLOCK


def questions_of(session: AgentSession, history: Sequence[Step]) -> list[QuestionView]:
    """The park on a person the session waits on, when it is no call's
    decision and nothing clears it by itself."""
    park = session.park
    if park is None or park.reason is not ParkReason.PERSON or waits_on_approval(park):
        return []
    parked = parked_step(history, park)
    if parked is None or not needs_person(park):
        return []
    return [
        QuestionView(
            session_id=session.id, seq=parked.seq, asked_at=parked.created_at, unlock=park.unlock
        )
    ]


def approvals_of(session: AgentSession, history: Sequence[Step]) -> list[ApprovalView]:
    """The calls a session parked on approval holds for a person's decision;
    none when it waits on nothing of the kind."""
    if not waits_on_approval(session.park):
        return []
    held: list[ApprovalView] = []
    for request in held_calls(history):
        header = request.header
        assert isinstance(header, ToolRequestHeader)
        held.append(
            ApprovalView(
                session_id=session.id,
                seq=request.seq,
                requested_at=request.created_at,
                tool=header.tool,
                authorization_class=header.authorization_class,
                principal_id=header.principal.id,
            )
        )
    return held


def tool_calls_of(history: Sequence[Step], now: datetime) -> list[ToolCallView]:
    """Every tool request in order, each with the latest decision a person
    made on it and the response that answered it. A decision reads as of
    its call's response when the call has one: an approval that let a
    call run stays approved once its lifetime passes."""
    decisions: dict[UUID, ControlHeader] = {}
    responses: dict[UUID, Step] = {}
    for step in history:
        header = step.header
        if isinstance(header, ControlHeader) and header.call is not None and step.refs:
            decisions[step.refs[0]] = header
        elif step.type is StepType.TOOL_RESPONSE and step.responds_to is not None:
            responses[step.responds_to] = step
    calls: list[ToolCallView] = []
    for step in history:
        header = step.header
        if not isinstance(header, ToolRequestHeader):
            continue
        decided = decisions.get(step.id)
        call = None if decided is None else decided.call
        answered = responses.get(step.id)
        answer = None if answered is None else answered.header
        as_of = now if answered is None else answered.created_at
        calls.append(
            ToolCallView(
                seq=step.seq,
                loop_id=step.loop_id,
                requested_at=step.created_at,
                tool=header.tool,
                authorization_class=header.authorization_class,
                principal_id=header.principal.id,
                decision=None if decided is None else verdict_of(decided, as_of),
                decided_by=None if call is None else call.decided_by,
                response_seq=None if answered is None else answered.seq,
                responded_at=None if answered is None else answered.created_at,
                failure=answer.failure if isinstance(answer, ToolResponseHeader) else None,
            )
        )
    return calls


def verdict_of(decided: ControlHeader, now: datetime) -> Verdict:
    if decided.command is ControlCommand.DENY:
        return Verdict.DENIED
    expires = None if decided.call is None else decided.call.expires_at
    return Verdict.EXPIRED if expires is not None and expires <= now else Verdict.APPROVED


def usage_of(history: Sequence[Step]) -> SessionModelUsageView:
    """The usage every model response reported, summed per model by the
    request it answers, and in total. A response with no usage reported
    counts as a call and adds no tokens."""
    fills: dict[UUID, str] = {}
    totals: dict[str, list[int]] = {}
    for step in history:
        header = step.header
        if isinstance(header, ModelRequestHeader):
            fills[step.id] = header.fill
        elif isinstance(header, ModelResponseHeader) and step.responds_to is not None:
            fill = fills.get(step.responds_to)
            if fill is None:
                continue
            used = header.usage
            row = totals.setdefault(fill, [0, 0, 0, 0, 0, 0])
            row[0] += 1
            if used is not None:
                for index, value in enumerate(
                    (used.input, used.cache_read, used.cache_write, used.output, used.thinking),
                    start=1,
                ):
                    row[index] += value
    per_fill = [
        FillUsageView(
            fill=fill,
            calls=row[0],
            input=row[1],
            cache_read=row[2],
            cache_write=row[3],
            output=row[4],
            thinking=row[5],
        )
        for fill, row in sorted(totals.items())
    ]
    return SessionModelUsageView(
        calls=sum(f.calls for f in per_fill),
        input=sum(f.input for f in per_fill),
        cache_read=sum(f.cache_read for f in per_fill),
        cache_write=sum(f.cache_write for f in per_fill),
        output=sum(f.output for f in per_fill),
        thinking=sum(f.thinking for f in per_fill),
        fills=per_fill,
    )


def bounds_of(kind: AgentKind, tree: AgentTree) -> BoundsView:
    limits = kind.limits
    return BoundsView(
        kind=kind.name,
        kind_version=kind.version,
        loop=LoopLimitsView(
            step_guard=limits.step_guard,
            error_streak=limits.error_streak,
            nudges=limits.nudges,
            run_time_seconds=limits.run_time.total_seconds(),
        ),
        kind_deadline_seconds=None if kind.deadline is None else kind.deadline.total_seconds(),
        tree=TreeBoundsView(
            root_id=tree.id,
            height=tree.height,
            count=tree.count,
            concurrency=tree.concurrency,
            deadline=tree.deadline,
            size=tree.size,
        ),
    )
