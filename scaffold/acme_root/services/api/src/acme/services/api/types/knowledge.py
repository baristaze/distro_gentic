"""Wire types of a tenant's knowledge: an entry as stored, one a person
writes or edits, and a person's review of a suggestion."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.knowledge.types.knowledge import MAX_TEXT, KnowledgeStatus
from acme.om.steps.types.content import MAX_NAME
from acme.services.api.types.common import RequestBody, View

MAX_TRIGGER_WORDS = 20


class KnowledgeRequest(RequestBody):
    """An entry: its title, the words that trigger it, all of which must
    appear in what a session is about, and what it says."""

    title: str = Field(min_length=1, max_length=MAX_NAME)
    trigger: list[str] = Field(min_length=1, max_length=MAX_TRIGGER_WORDS)
    text: str = Field(min_length=1, max_length=MAX_TEXT)


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
