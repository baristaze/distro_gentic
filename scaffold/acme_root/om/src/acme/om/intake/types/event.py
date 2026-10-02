"""An event from outside, as an integration hands it to the router: what
arrived, who wrote it, and the work it names. The integration reads these
fields from what its system reports. The router decides the rest: which
session it reaches, whether it wakes it, and in whose name it speaks."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import Platform
from acme.om.steps.types.content import MAX_NAME, Stored

MAX_TEXT = 20_000
"""The most of an event's text a session receives; the rest is cut."""

MAX_REFS = 20


class Arrival(StrEnum):
    """What arrived. The answer decides the event's row of the routing
    table, with who wrote it."""

    MESSAGE = "message"  # someone addresses the agent, as in chat
    COMMENT = "comment"  # a comment on the agent's work
    TICKET = "ticket"  # a ticket reopened or reassigned to the agent
    CHECK = "check"  # a check on the agent's work finished
    CI_OUTPUT = "ci_output"  # a line of CI output
    PUSH = "push"  # a push to the agent's branch


class AuthorKind(StrEnum):
    """Who wrote it, as the integration's system says."""

    PERSON = "person"
    BOT = "bot"
    PLATFORM = "platform"  # the platform's own account: an agent's act


class CheckState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class Author(Platform):
    """The account behind an event in the integration's system: its kind,
    its id there, and the name it shows. A person's id is what an account
    link maps to a user of the tenant."""

    kind: AuthorKind
    external_id: Stored = Field(min_length=1, max_length=MAX_NAME)
    name: Stored = Field(min_length=1, max_length=MAX_NAME)


class WorkNames(Platform):
    """The work an event names: a session by its id, a pull request, or a
    branch, each as the integration spells it. The router tries them in
    that order."""

    session_id: UUID | None = None
    pull_request: Stored | None = Field(default=None, min_length=1, max_length=MAX_NAME)
    branch: Stored | None = Field(default=None, min_length=1, max_length=MAX_NAME)


class FeedbackEvent(Platform):
    """One event from outside. `id` is derived from the delivery that carried
    it, so a redelivery is the same event. `integration` names the system
    it came from, and `text` is what it says, which reaches a session as
    data unless a principal wrote it. `refs` are the integration's own
    names for what the event is and what it follows from, such as a
    comment's id or the commit a check ran on: an act of the platform's
    account recorded under one of them is the event's cause."""

    id: UUID
    integration: Stored = Field(min_length=1, max_length=MAX_NAME)
    arrival: Arrival
    author: Author
    names: WorkNames
    refs: tuple[Annotated[Stored, Field(min_length=1, max_length=MAX_NAME)], ...] = Field(
        default=(), max_length=MAX_REFS
    )
    text: Stored = Field(default="", max_length=MAX_TEXT)
    check: CheckState | None = None
    occurred_at: datetime

    @model_validator(mode="after")
    def _a_check_has_a_state(self) -> Self:
        if (self.arrival is Arrival.CHECK) != (self.check is not None):
            raise ValueError("a check says whether it passed, and nothing else does")
        return self


class ChatApproval(Platform):
    """A person's yes or no to one tool call, clicked in chat: the chat
    account that clicked, and the call it decides by its session and its
    place in the history."""

    integration: Stored = Field(min_length=1, max_length=MAX_NAME)
    external_id: Stored = Field(min_length=1, max_length=MAX_NAME)
    session_id: UUID
    request_seq: int = Field(ge=1)
    approve: bool
    note: Stored = Field(default="", max_length=MAX_TEXT)
