"""Knowledge: what a new session should not have to rediscover about its
environment, recalled into it when its trigger matches. It renders as
data. An agent may suggest it; a person reviews it before any session
recalls it."""

from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import Field

from acme.om.base import Identifiable, Trackable
from acme.om.steps.types.content import MAX_NAME, Stored

MAX_TEXT = 10_000


class KnowledgeStatus(StrEnum):
    SUGGESTED = "suggested"  # an agent's suggestion, waiting for a person
    REVIEWED = "reviewed"  # a person read it and let it be recalled
    REJECTED = "rejected"


class Knowledge(Identifiable, Trackable):
    """One entry: the words that trigger it, all of which must appear in what
    a session is about, and what it says. `suggested_by` is the session
    whose agent suggested it; `reviewed_by` the person who decided."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = ("status", "reviewed_by", "version")

    trigger: tuple[Stored, ...] = Field(min_length=1, max_length=20)
    text: Stored = Field(min_length=1, max_length=MAX_TEXT)
    status: KnowledgeStatus = KnowledgeStatus.SUGGESTED
    suggested_by: UUID | None = None
    reviewed_by: UUID | None = None
    title: Stored = Field(min_length=1, max_length=MAX_NAME)
    version: int = Field(default=1, ge=1)
