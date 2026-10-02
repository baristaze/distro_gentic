"""A playbook: a team's procedure as a versioned, executable brief, in the
Agent Skills format, with its approval gates in a namespaced metadata
extension. And an invocation: a playbook a principal brought into one
session, whose gates join that session's policy."""

from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import Created, Identifiable, Platform
from acme.om.steps.types.content import MAX_NAME, Stored
from acme.om.tools.types.policy import Decision
from acme.om.tools.types.tool import CLASS_NAME, TOOL_NAME

SKILL_NAME = r"^[a-z0-9]+(-[a-z0-9]+)*$"
"""A skill's name as the Agent Skills standard spells it: lowercase words
joined by single hyphens."""

MAX_SKILL_NAME = 64
MAX_DESCRIPTION = 1024
MAX_BODY = 50_000


class PlaybookGate(Platform):
    """One gate: the calls it selects, by tool or by class, and what they
    need. A gate asks for a person's approval or denies; it never allows,
    so it can only narrow what the session's policy lets run."""

    tool: str | None = Field(default=None, pattern=TOOL_NAME)
    authorization_class: str | None = Field(default=None, pattern=CLASS_NAME)
    decision: Decision

    @model_validator(mode="after")
    def _selects_and_narrows(self) -> Self:
        if self.tool is None and self.authorization_class is None:
            raise ValueError("a gate selects its calls by tool or by class")
        if self.decision is Decision.ALLOW:
            raise ValueError("a gate asks for approval or denies; it never allows")
        return self


class PlaybookDraft(Platform):
    """What a person publishes: the brief's name and description, its body
    (what is needed, the steps, the safety requirements, the success
    measures, what is forbidden), and its gates."""

    name: Stored = Field(min_length=1, max_length=MAX_SKILL_NAME, pattern=SKILL_NAME)
    description: Stored = Field(min_length=1, max_length=MAX_DESCRIPTION)
    body: Stored = Field(min_length=1, max_length=MAX_BODY)
    gates: tuple[PlaybookGate, ...] = ()


class Playbook(Identifiable, Created):
    """One published version of a playbook. A version is written once; a
    change is the next version."""

    name: Stored = Field(min_length=1, max_length=MAX_SKILL_NAME, pattern=SKILL_NAME)
    version: int = Field(ge=1)
    description: Stored = Field(min_length=1, max_length=MAX_DESCRIPTION)
    body: Stored = Field(min_length=1, max_length=MAX_BODY)
    gates: tuple[PlaybookGate, ...] = ()
    published_by: UUID


class PlaybookInvocation(Identifiable, Created):
    """A playbook version brought into a session by a principal. Its gates
    hold in that session from then on."""

    session_id: UUID
    playbook_id: UUID
    name: Stored = Field(min_length=1, max_length=MAX_NAME)
    version: int = Field(ge=1)
    invoked_by: UUID
