"""Wire types of a tenant's knowledge: an entry as stored, one a person
writes or edits, and a person's review of a suggestion."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from acme.om.knowledge.rules import words
from acme.om.knowledge.types.knowledge import MAX_TEXT, KnowledgeStatus
from acme.om.steps.types.content import MAX_NAME
from acme.services.api.types.common import RequestBody, View

MAX_TRIGGER_WORDS = 20


class KnowledgeRequest(RequestBody):
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


class KnowledgeView(View):
    """An entry, its state, who suggested and who reviewed it, and the
    version an edit names in `If-Match`."""

    id: UUID
    title: str
    trigger: list[str]
    text: str
    status: KnowledgeStatus
    suggested_by: UUID | None
    reviewed_by: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime
