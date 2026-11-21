"""Agent knowledge: what a new session should not have to rediscover about its
environment, recalled into it when its trigger matches, and searched and
read by its agent on demand. It renders as data. An agent may suggest it;
a person reviews it before any session recalls or reads it. An entry
belongs to one agent project of its tenant, or to the whole tenant. A
kind's own entry belongs to no tenant: it ships in its kind's folder, and
every session of its kind reaches it."""

from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import Field

from acme.om.agent_steps.types.content import MAX_NAME, Stored
from acme.om.base import Created, Identifiable, OmBase, Trackable
from acme.om.levers.types.lever import LeverFinding

MAX_TEXT = 10_000
MAX_SLUG = 80
SLUG = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class AgentKnowledgeStatus(StrEnum):
    SUGGESTED = "suggested"  # an agent's suggestion, waiting for a person
    REVIEWED = "reviewed"  # a person read it and let it be recalled
    REJECTED = "rejected"


class AgentKnowledge(Identifiable, Trackable):
    """One entry: the words that trigger it, all of which must appear in what
    a session is about, and what it says. `suggested_by` is the session
    whose agent suggested it; `reviewed_by` the person who decided.
    `agent_project_id` is the agent project whose sessions reach it, None for every
    session of the tenant; `slug` is the handle an agent reads it by, None
    on a row an earlier release wrote. `findings` is what the lever checks
    read in its words at this version: advice for the person who reviews
    it, never a refusal; None on a version they never read, one an earlier
    release wrote."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = (
        "status",
        "reviewed_by",
        "version",
        "agent_project_id",
        "slug",
        "findings",
    )

    trigger: tuple[Stored, ...] = Field(min_length=1, max_length=20)
    text: Stored = Field(min_length=1, max_length=MAX_TEXT)
    status: AgentKnowledgeStatus = AgentKnowledgeStatus.SUGGESTED
    suggested_by: UUID | None = None
    reviewed_by: UUID | None = None
    title: Stored = Field(min_length=1, max_length=MAX_NAME)
    version: int = Field(default=1, ge=1)
    agent_project_id: UUID | None = None
    slug: str | None = Field(default=None, max_length=MAX_SLUG, pattern=SLUG)
    findings: tuple[LeverFinding, ...] | None = None


class AgentKnowledgeRecall(Identifiable, Created):
    """An entry's version a session recalled, or an agent of it read by its
    slug: which lever it reached, kept so a reading of the sessions that
    stalled can name it."""

    agent_session_id: UUID
    entry_id: UUID
    version: int = Field(ge=1)


class KindEntry(OmBase):
    """An entry a kind ships in its folder's `wiki/`: the kind's own, never a
    tenant's. Every session of its kind reaches it, whatever its tenant
    and its agent project; a session of another kind never does. No tenant
    writes, reviews, edits, or erases it, and no recall of it is recorded,
    since it is no tenant's lever: it is reviewed as its kind's code is.
    `slug` is its handle among its kind's entries, and an agent reads it by
    its kind's name and its slug (`handle`), which no tenant's slug
    matches."""

    kind: str = Field(min_length=1, max_length=MAX_NAME)
    slug: str = Field(max_length=MAX_SLUG, pattern=SLUG)
    title: Stored = Field(min_length=1, max_length=MAX_NAME)
    trigger: tuple[Stored, ...] = Field(min_length=1, max_length=20)
    text: Stored = Field(min_length=1, max_length=MAX_TEXT)

    @property
    def handle(self) -> str:
        """What an agent reads the entry by: `<kind>/<slug>`. A tenant's slug
        holds no `/`, so the two never meet."""
        return f"{self.kind}/{self.slug}"
