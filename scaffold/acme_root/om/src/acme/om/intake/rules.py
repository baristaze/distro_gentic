"""Pure rules of the router: the routing table, and the input a session
receives for each row. Values in, values out; no storage, no clock.

The table, row by row:

| Arrival | Effect |
|---|---|
| A principal's message | Wakes; unarchives an archived session |
| A comment by a mapped user who may instruct the session | Wakes, as that principal's message |
| Any other person's comment | Wakes, as data |
| A ticket reopened or reassigned to the agent | Wakes |
| A bot's comment, a line of CI output | Waits in the inbox |
| A failing check | Wakes |
| A passing check | Waits |
| A person's push to the agent's branch | Hands the session over |
| Anything for an archived session | Recorded only |

Only a mapped user's words become a message; everything else from outside
is an event, which the engine renders as data, quoted, with the origin set
here: `integration`, by an `external` actor. Nothing an event says sets
either. The session's own acts, which come back through the integration
as the platform's account, are audited and never delivered."""

from datetime import datetime
from uuid import UUID

from acme.om.attribution.types.principal import Principal
from acme.om.base import Platform, derived_id
from acme.om.context import CredentialKind, TenantContext
from acme.om.intake.types.event import MAX_TEXT, Arrival, AuthorKind, CheckState, FeedbackEvent
from acme.om.intake.types.route import Effect
from acme.om.steps.types.content import Content, TextBlock
from acme.om.steps.types.header import InputHeader
from acme.om.steps.types.step import Actor, Origin, Step, StepType

DELIVERED = frozenset({Effect.WAKE, Effect.WAKE_AS_DATA, Effect.WAIT, Effect.RECORD})
"""The effects that land an input in the session's history."""

WAKES = frozenset({Effect.WAKE, Effect.WAKE_AS_DATA})


class Facts(Platform):
    """What the table reads of one event in one session: what arrived, who
    wrote it, a check's state, whether the session is archived, and whether
    the author is a mapped user who may instruct the session."""

    arrival: Arrival
    author: AuthorKind
    check: CheckState | None = None
    archived: bool = False
    instructs: bool = False


def effect_of(facts: Facts) -> Effect:
    """The one effect the routing table gives an event. A principal is a
    person; a bot or the platform's account never instructs, whatever link
    it has."""
    if facts.author is AuthorKind.PLATFORM:
        return Effect.OWN
    principal = facts.author is AuthorKind.PERSON and facts.instructs
    if facts.archived:
        # Only a principal's message brings an archived session back.
        return Effect.WAKE if principal and facts.arrival is Arrival.MESSAGE else Effect.RECORD
    match facts.arrival:
        case Arrival.MESSAGE | Arrival.COMMENT:
            if facts.author is AuthorKind.BOT:
                return Effect.WAIT
            return Effect.WAKE if principal else Effect.WAKE_AS_DATA
        case Arrival.TICKET:
            return Effect.WAKE_AS_DATA
        case Arrival.CI_OUTPUT:
            return Effect.WAIT
        case Arrival.CHECK:
            return Effect.WAKE_AS_DATA if facts.check is CheckState.FAILED else Effect.WAIT
        case Arrival.PUSH:
            return Effect.HAND_OVER if facts.author is AuthorKind.PERSON else Effect.WAIT


def in_person(ctx: TenantContext) -> bool:
    """Whether a person is at the product surface themselves: signed in on a
    session of their own. A call an agent makes runs under its principal's
    live context, which is internal, and a program speaks on an API key:
    neither is a person in person."""
    return ctx.credential_kind is CredentialKind.SESSION_TOKEN


ARRIVALS: dict[Arrival, str] = {
    Arrival.MESSAGE: "message",
    Arrival.COMMENT: "comment",
    Arrival.TICKET: "ticket reopened or reassigned to the agent",
    Arrival.CHECK: "check",
    Arrival.CI_OUTPUT: "CI output",
    Arrival.PUSH: "push",
}


def described(event: FeedbackEvent) -> str:
    """An event as the agent reads it, as data: a first line the platform
    writes from the fields the integration read, then what it says, its end
    cut so the whole stays within the text an event may carry."""
    on = event.names.pull_request or event.names.branch
    what = ARRIVALS[event.arrival]
    if event.check is not None:
        what = f"{what} {event.check.value}"
    head = f"{event.integration}: {what} by {event.author.kind.value} {event.author.name}"
    head = f"{head} on {on}" if on else head
    if not event.text:
        return head[:MAX_TEXT]
    room = max(MAX_TEXT - len(head) - 1, 0)
    return f"{head}\n{event.text[:room]}"[:MAX_TEXT]


def input_step(
    event: FeedbackEvent,
    session_id: UUID,
    effect: Effect,
    principal: Principal,
    now: datetime,
) -> Step:
    """The input a session receives for an effect that delivers one. A
    principal's message speaks in `principal`'s name: the mapped user's,
    whose context appends it. Any other input is an event under
    `principal`, the router's: data, which never instructs. Its id is
    derived from the event's, so a redelivery appends nothing."""
    if effect not in DELIVERED:
        raise ValueError(f"{effect.value} delivers no input")
    step_id = derived_id(event.id, event.occurred_at, "intake:input")
    message = effect is Effect.WAKE
    return Step(
        id=step_id,
        created_at=now,
        session_id=session_id,
        loop_id=step_id,
        type=StepType.MESSAGE if message else StepType.EVENT,
        actor=Actor.PERSON if message else Actor.EXTERNAL,
        origin=Origin.INTEGRATION,
        header=InputHeader(waking=effect in WAKES, principal=principal),
        content=Content(blocks=(TextBlock(text=event.text if message else described(event)),)),
    )
