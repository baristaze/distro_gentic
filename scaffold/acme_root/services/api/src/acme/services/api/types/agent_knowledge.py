"""Wire types of a tenant's agent knowledge: an entry as stored, one a person
writes or edits, and a person's review of a suggestion."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from acme.om.agent_knowledge.rules import words
from acme.om.agent_knowledge.types.agent_knowledge import MAX_TEXT, AgentKnowledgeStatus
from acme.om.agent_steps.types.content import MAX_NAME
from acme.services.api.types.common import RequestBody, View
from acme.services.api.types.levers import FindingView

MAX_TRIGGER_WORDS = 20


class AgentKnowledgeRequest(RequestBody):
    """An entry: its title, the words that trigger it, all of which must
    appear in what a session is about, and what it says. A trigger word
    with none of a-z, 0-9, `_`, `.` or `-` is refused: recall reads nothing
    in it, so it would match every session."""

    title: str = Field(min_length=1, max_length=MAX_NAME)
    trigger: list[str] = Field(min_length=1, max_length=MAX_TRIGGER_WORDS)
    text: str = Field(min_length=1, max_length=MAX_TEXT)

    @field_validator("trigger")
    @classmethod
    def _each_word_matches_something(cls, trigger: list[str]) -> list[str]:
        if any(not words(word) for word in trigger):
            raise ValueError("each trigger word holds one of a-z, 0-9, _, . or - at least")
        return trigger


class ReviewRequest(RequestBody):
    """Keep a suggestion, so any session may recall it, or reject it."""

    keep: bool


class AgentKnowledgeView(View):
    """An entry, its state, who suggested and who reviewed it, the version
    an edit names in `If-Match`, and what the lever checks found in its
    words at that version: advice, never a refusal; null on a version they
    never read, an empty list on one they read and found nothing in."""

    id: UUID
    title: str
    trigger: list[str]
    text: str
    status: AgentKnowledgeStatus
    suggested_by: UUID | None
    reviewed_by: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime
    findings: list[FindingView] | None
