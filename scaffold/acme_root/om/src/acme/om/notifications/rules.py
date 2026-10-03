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
- Any other park on a person, or a call past its own amount: answer the
  session; its requester, or, when they hold no place now, the members
  who manage the tenant.

A link names a route the API serves: a call's decision, the session's
controls, and a budget's amount. An action no route serves yet (topping
up, approving a call past its norm) carries none, and its text names the
park instead.

A park on a price waits for the platform's operator, whom no tenant's
member stands in for, and tells nobody here."""

from collections.abc import Iterable, Sequence
from uuid import UUID

from acme.om.base import derived_id
from acme.om.billing.rules import FUNDS_UNLOCK
from acme.om.budgets.rules import OWN_AMOUNT_UNLOCK
from acme.om.context import Permission, Role
from acme.om.steps.types.header import Park, ParkedHeader, ParkReason, ToolRequestHeader
from acme.om.steps.types.step import Step, StepType
from acme.om.tenancy.rules import permissions_of
from acme.om.tenancy.types.membership import Membership

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


def decision_link(session_id: UUID, request: Step) -> str:
    return f"/v1/agent-sessions/{session_id}/calls/{request.seq}/decision"


def answer_link(session_id: UUID) -> str:
    return f"/v1/agent-sessions/{session_id}/controls"


def budget_link(budget_id: UUID) -> str:
    return f"/v1/budgets/{budget_id}/amount"


NO_ROUTE = ""
"""The link of an action no route of the API serves yet: topping up the
account, and approving a call past its norm. Each such ask names its park
in its text; it takes a link when its route comes."""


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
