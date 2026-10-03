"""Knowledge: what a new session should not have to rediscover about its
environment, recalled into it when its trigger matches, and searched and
read by its agent on demand. It renders as data. An agent may suggest it;
a person reviews it before any session recalls or reads it. An entry
belongs to one project of its tenant, or to the whole tenant."""

from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import Field

from acme.om.base import Identifiable, Trackable
from acme.om.steps.types.content import MAX_NAME, Stored

MAX_TEXT = 10_000
MAX_SLUG = 80
SLUG = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class KnowledgeStatus(StrEnum):
    SUGGESTED = "suggested"  # an agent's suggestion, waiting for a person
    REVIEWED = "reviewed"  # a person read it and let it be recalled
    REJECTED = "rejected"


class Knowledge(Identifiable, Trackable):
    """One entry: the words that trigger it, all of which must appear in what
    a session is about, and what it says. `suggested_by` is the session
    whose agent suggested it; `reviewed_by` the person who decided.
    `project_id` is the project whose sessions reach it, None for every
    session of the tenant; `slug` is the handle an agent reads it by, None
    on a row an earlier release wrote."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = (
        "status",
        "reviewed_by",
        "version",
        "project_id",
        "slug",
    )

    trigger: tuple[Stored, ...] = Field(min_length=1, max_length=20)
    text: Stored = Field(min_length=1, max_length=MAX_TEXT)
    status: KnowledgeStatus = KnowledgeStatus.SUGGESTED
    suggested_by: UUID | None = None
    reviewed_by: UUID | None = None
    title: Stored = Field(min_length=1, max_length=MAX_NAME)
    version: int = Field(default=1, ge=1)
    project_id: UUID | None = None
    slug: str | None = Field(default=None, max_length=MAX_SLUG, pattern=SLUG)
