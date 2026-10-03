"""Pure rules of notifications: which parks need a person, the one action
that clears each, its link, and who may take it. Values in, values out.

A park needs a person when nothing clears it by itself: it carries no
retry time. Each such park asks one action of exactly the people who may
take it:

- A call held for approval: decide the call; the members whose role the
  tenant's policy lets decide the call's class.
- A budget a person must raise: raise it; the members who set budgets.
- The account's funds: top up; the members who set budgets.
- A call far above its session's norm: approve it; the members who
  approve such calls.
- A question the agent asked its person: answer it with a message; its
  requester, or, when they hold no place now, the members who manage the
  tenant. The text quotes the question.
- Any other park on a person, or a call past its own amount: answer the
  session; the same people.

A link names a route the API serves: a call's decision, the session's
messages, the session's controls, and a budget's amount. An action no
route serves yet (topping up, approving a call past its norm) carries
none, and its text names the park instead.

A park on a price waits for the platform's operator, whom no tenant's
member stands in for, and tells nobody here."""

import html
import json
from collections.abc import Iterable, Sequence
from uuid import UUID

from acme.om.base import derived_id
from acme.om.billing.rules import FUNDS_UNLOCK
from acme.om.budgets.rules import OWN_AMOUNT_UNLOCK
from acme.om.context import Permission, Role
from acme.om.steps.types.content import TextBlock
from acme.om.steps.types.header import (
    Park,
    ParkedHeader,
    ParkReason,
    ToolRequestHeader,
    ToolResponseHeader,
)
from acme.om.steps.types.step import Step, StepType
from acme.om.tenancy.rules import permissions_of
from acme.om.tenancy.types.membership import Membership
from acme.om.tools.native.ask_person import ASK_PERSON
from acme.om.workspaces.rules import AUTHORITY, FETCHED, SCHEMED, WWW

NOTIFIED = frozenset({ParkReason.PERSON, ParkReason.BUDGET})
"""The reasons whose park can wait on a person of the tenant."""

SETS_BUDGETS = Permission.MANAGE_MEMBERS
"""What raising a budget asks, as the budgets swimlane holds it."""

APPROVES_CALLS = Permission.MANAGE_MEMBERS
"""What approving a call past its session's norm asks, as billing holds it
(`approve_call`)."""


def needs_person(park: Park) -> bool:
    """Whether a park waits on a person of the tenant: nothing clears it by
    itself, and it is not a price only the operator sets."""
    if park.reason not in NOTIFIED or park.retry_at is not None:
        return False
    if park.reason is ParkReason.PERSON:
        return True
    return as_budget(park.unlock) is not None or park.unlock in (OWN_AMOUNT_UNLOCK, FUNDS_UNLOCK)


def as_budget(unlock: str) -> UUID | None:
    """The budget a budget park names, when it names one."""
    try:
        return UUID(unlock)
    except ValueError:
        return None


def held_calls(history: Sequence[Step]) -> list[Step]:
    """The calls a session holds for a person's decision: its tool requests
    that no tool response answers yet."""
    answered = {s.responds_to for s in history if s.type is StepType.TOOL_RESPONSE}
    return [
        step
        for step in history
        if isinstance(step.header, ToolRequestHeader) and step.id not in answered
    ]


def holding(members: Iterable[Membership], roles: Iterable[Role]) -> tuple[UUID, ...]:
    """The members in one of `roles`, by user id."""
    wanted = set(roles)
    return tuple(sorted({m.user_id for m in members if m.role in wanted}))


def holding_permission(members: Iterable[Membership], permission: Permission) -> tuple[UUID, ...]:
    """The members whose role holds `permission`."""
    return tuple(sorted({m.user_id for m in members if permission in permissions_of(m.role)}))


def requester_or_managers(requester: UUID, members: Sequence[Membership]) -> tuple[UUID, ...]:
    """Who answers a session: its requester, while they hold a place in the
    tenant; else the members who manage it."""
    if any(member.user_id == requester for member in members):
        return (requester,)
    return holding_permission(members, Permission.MANAGE_MEMBERS)


def decision_link(session_id: UUID, request: Step) -> str:
    return f"/v1/agent-sessions/{session_id}/calls/{request.seq}/decision"


def answer_link(session_id: UUID) -> str:
    return f"/v1/agent-sessions/{session_id}/controls"


def message_link(session_id: UUID) -> str:
    return f"/v1/agent-sessions/{session_id}/messages"


def budget_link(budget_id: UUID) -> str:
    return f"/v1/budgets/{budget_id}/amount"


NO_ROUTE = ""
"""The link of an action no route of the API serves yet: topping up the
account, and approving a call past its norm. Each such ask names its park
in its text; it takes a link when its route comes."""


ANSWER_QUESTION = "answer_question"
"""The action a question asks: its person's answer, which a message is."""

QUOTED = 250
"""The most characters of a question a notification quotes; the session
holds it whole. Escaped, it fits the notification's text beside the
session's title."""

LINKS = (FETCHED, AUTHORITY, SCHEMED, WWW)
"""What a surface may fetch or link: an image, an element that loads a URL,
and a URL's host, as a pull request's body is read for them."""


def asked_question(history: Sequence[Step]) -> str | None:
    """The question a session waits on: the latest `ask_person` call the
    history answers without a failure, as its answer holds it. None when
    that answer holds no question."""
    asks = {
        step.id
        for step in history
        if isinstance(step.header, ToolRequestHeader) and step.header.tool == ASK_PERSON
    }
    question: str | None = None
    for step in history:
        header = step.header
        if (
            step.responds_to in asks
            and isinstance(header, ToolResponseHeader)
            and header.failure is None
        ):
            question = _question_of(step)
    return question


def _question_of(answer: Step) -> str | None:
    parts = answer.as_tool_response().parts
    if not parts or not isinstance(parts[0], TextBlock):
        return None
    try:
        value = json.loads(parts[0].text)
    except ValueError:
        return None
    question = value.get("question") if isinstance(value, dict) else None
    return question if isinstance(question, str) and question.strip() else None


def quoted(question: str) -> str | None:
    """A question as a notification quotes it: on one line, its whitespace
    collapsed, cut to `QUOTED` characters, and escaped as a JSON string is,
    so nothing in it closes its quote. None when it holds what a surface may
    fetch or link, read as written and with its character references
    resolved: a notification carries no URL the agent wrote."""
    line = " ".join(question.split())
    if any(pattern.search(text) for text in (line, html.unescape(line)) for pattern in LINKS):
        return None
    if len(line) > QUOTED:
        line = f"{line[: QUOTED - 1]}…"
    return json.dumps(line, ensure_ascii=False)


def question_text(title: str, question: str | None) -> str:
    """What a question's notification says: the question, quoted, when it
    can be; else that one waits in the session."""
    shown = None if question is None else quoted(question)
    if shown is None:
        return f"{title} asks you a question: read it in the session, and answer with a message."
    return f"{title} asks you: {shown} Answer with a message in the session."


def parked_step(history: Sequence[Step], park: Park) -> Step | None:
    """The step that wrote the park the session waits on: the latest
    `parked` step, when it carries that park."""
    for step in reversed(history):
        if step.type is StepType.PARKED:
            header = step.header
            return step if isinstance(header, ParkedHeader) and header.park == park else None
    return None


def notification_id(parked: Step, action: str, link: str, recipient: UUID, channel: str) -> UUID:
    """One park tells one recipient of one action once on each channel: the
    step that wrote the park is the park."""
    return derived_id(parked.id, parked.created_at, f"notify:{action}:{link}:{recipient}:{channel}")
