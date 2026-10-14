"""Pure rules of park alerts: which parks need a person, the one action
that clears each, its link, and who may take it. Values in, values out.

A park needs a person when nothing clears it by itself: it carries no
retry time. A park on the org's own account or key at a model provider
needs one too: it tries again by itself, and no try goes through until
an admin of the org fixes it there. Each such park asks one action of
exactly the people who may take it:

- A call held for approval: decide the call; the members whose role the
  tenant's policy lets decide the call's class.
- A budget a person must raise: raise it; the members who set budgets.
- The account's funds: top up; the members who set budgets.
- A call far above its session's norm: approve it; the members who
  approve such calls.
- A key the org holds none of, to a provider its call needs: save one;
  the members who save the org's keys. The text says why it waits, and
  who acts.
- The org's own account at a model provider, or a permission its key
  lacks there: fix it at the provider; the members who manage the org.
  The text says why it waits, and who acts. It is told once, at its
  first try: the tries after it are the same park.
- A question the agent asked its person: answer it with a message; its
  requester, or, when they hold no place now, the members who manage the
  tenant. The text quotes the question.
- Any other park on a person, or a call past its own amount: answer the
  session; the same people.

A link names a route the API serves: a call's decision, the session's
messages, the session's controls, a budget's amount, a call's approval
past its norm, and a provider's key. Topping up is paid at the payment
provider, and a fix at a model provider is made there: no route of the
API is either, so they carry none, and their text names the park
instead.

A park on a price, or on a key or an account the platform's operator
fixes, waits for that operator, whom no tenant's member stands in for,
and tells nobody here. Each tries again by itself."""

import html
import json
from collections.abc import Iterable, Sequence
from uuid import UUID

from acme.om.agent_billing.rules import FUNDS_UNLOCK
from acme.om.agents.loop_rules import fix_cause
from acme.om.base import derived_id
from acme.om.budgets.rules import OWN_AMOUNT_UNLOCK
from acme.om.context import Permission, Role
from acme.om.steps.types.content import TextBlock
from acme.om.steps.types.header import (
    ModelResponseHeader,
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

NOTIFIED = frozenset({ParkReason.PERSON, ParkReason.BUDGET, ParkReason.PROVIDER})
"""The reasons whose park can wait on a person of the tenant."""

SETS_BUDGETS = Permission.MANAGE_MEMBERS
"""What raising a budget asks, as the budgets swimlane holds it."""

APPROVES_CALLS = Permission.MANAGE_MEMBERS
"""What approving a call past its session's norm asks, as agent billing holds it
(`approve_call`)."""

SAVES_KEYS = Permission.MANAGE_MEMBERS
"""What saving the org's key to a provider asks, as trust holds it
(`save_provider_key`)."""

FIXES_AT_PROVIDER = Permission.MANAGE_MEMBERS
"""Who fixes the org's own account or key at a model provider: the members
who manage the org, the admins its park's cause names."""

MISSING_KEY = "key"
"""The cause a provider park names when the org holds no key to it."""

FIXED_AT_PROVIDER = frozenset({"billing", "permission"})
"""The causes of a provider park that only a fix at the provider clears:
the account's billing, and a permission, a region, or a model the key
cannot reach. A key the provider refused parks on the missing key at its
next try, which is told."""


def needs_person(park: Park) -> bool:
    """Whether a park waits on a person of the tenant: nothing clears it by
    itself, or it is a fix an admin of the org makes at a model provider;
    and it is not a price only the operator sets."""
    if park.reason not in NOTIFIED:
        return False
    if fixed_at_provider(park) is not None:
        return True
    if park.retry_at is not None:
        return False
    if park.reason is ParkReason.PERSON:
        return True
    if park.reason is ParkReason.PROVIDER:
        return missing_key(park) is not None
    return as_budget(park.unlock) is not None or park.unlock in (OWN_AMOUNT_UNLOCK, FUNDS_UNLOCK)


def fixed_at_provider(park: Park) -> str | None:
    """The model provider at which an admin of the org fixes the org's own
    account or key, when a provider park waits on one: the loop names the
    provider, then the cause, and its cause names an admin of the org as
    who acts, never an operator of the platform."""
    provider, _, cause = park.unlock.partition(":")
    if park.reason is not ParkReason.PROVIDER or cause not in FIXED_AT_PROVIDER or not provider:
        return None
    return provider if park.cause == fix_cause(provider, cause, tenants=True) else None


def missing_key(park: Park) -> str | None:
    """The provider a provider park waits for the org's key to, when it
    waits for one: the loop names it, then the cause."""
    provider, _, cause = park.unlock.partition(":")
    if park.reason is not ParkReason.PROVIDER or cause != MISSING_KEY or not provider:
        return None
    return provider


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


def approval_link(session_id: UUID) -> str:
    return f"/v1/agent-sessions/{session_id}/cost-approval"


def key_link(provider: str) -> str:
    return f"/v1/provider-keys/{provider}"


NO_ROUTE = ""
"""The link of an action no route of the API serves: topping up the
account, which the payment provider takes, and a fix at a model provider,
made there. Such an ask names its park in its text."""


ANSWER_QUESTION = "answer_question"
"""The action a question asks: its person's answer, which a message is."""

QUOTED = 250
"""The most characters of a question a park alert quotes; the session
holds it whole. Escaped, it fits the park alert's text beside the
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
    """A question as a park alert quotes it: on one line, its whitespace
    collapsed, cut to `QUOTED` characters, and escaped as a JSON string is,
    so nothing in it closes its quote. None when it holds what a surface may
    fetch or link, read as written and with its character references
    resolved: a park alert carries no URL the agent wrote."""
    line = " ".join(question.split())
    if any(pattern.search(text) for text in (line, html.unescape(line)) for pattern in LINKS):
        return None
    if len(line) > QUOTED:
        line = f"{line[: QUOTED - 1]}…"
    return json.dumps(line, ensure_ascii=False)


def question_text(title: str, question: str | None) -> str:
    """What a question's park alert says: the question, quoted, when it
    can be and is given; else that one waits in the session. The row a
    park alert leaves is told none, so it quotes nothing sealed."""
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


def first_try(history: Sequence[Step], parked: Step) -> Step:
    """The step that wrote the first try of the park `parked` wrote again: a
    park that tries again by itself is written at each try, and is the same
    park until the session parks on something else, a call is answered, or
    its loop ends."""
    header = parked.header
    assert isinstance(header, ParkedHeader)
    same = (header.park.reason, header.park.unlock)
    first = parked
    for step in reversed(history):
        earlier = step.header
        if step.seq >= parked.seq:
            continue
        if step.type is StepType.LOOP_ENDED:
            break
        if isinstance(earlier, ModelResponseHeader) and not earlier.abandoned:
            break  # a call was answered
        if isinstance(earlier, ParkedHeader):
            if (earlier.park.reason, earlier.park.unlock) != same:
                break
            first = step
    return first


def park_alert_id(parked: Step, action: str, link: str, recipient: UUID, channel: str) -> UUID:
    """One park tells one recipient of one action once on each channel: the
    step that wrote the park is the park, and for a park that tries again
    by itself, the step that wrote its first try (`first_try`)."""
    return derived_id(parked.id, parked.created_at, f"notify:{action}:{link}:{recipient}:{channel}")
