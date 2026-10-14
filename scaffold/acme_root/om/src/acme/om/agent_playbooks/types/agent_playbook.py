"""An agent playbook: a team's procedure as a versioned, executable brief, in the
Agent Skills format, with its approval gates in a namespaced metadata
extension. An invocation: an agent playbook brought into one session, whose gates
join that session's policy. And a pin: a version a tenant set as a kind's
kind manual, which each new session of the kind holds as its standing text."""

from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.attribution.types.principal import MAX_KIND
from acme.om.base import Created, Identifiable, Platform, Trackable
from acme.om.levers.types.lever import LeverFinding
from acme.om.steps.types.content import MAX_NAME, Stored
from acme.om.tools.types.policy import Decision
from acme.om.tools.types.tool import CLASS_NAME, TOOL_NAME

SKILL_NAME = r"^[a-z0-9]+(-[a-z0-9]+)*$"
"""A skill's name as the Agent Skills standard spells it: lowercase words
joined by single hyphens."""

MAX_SKILL_NAME = 64
MAX_DESCRIPTION = 1024
MAX_BODY = 50_000


class AgentPlaybookGate(Platform):
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


class AgentPlaybookDraft(Platform):
    """What a person publishes: the brief's name and description, its body
    (what is needed, the steps, the safety requirements, the success
    measures, what is forbidden), and its gates."""

    name: Stored = Field(min_length=1, max_length=MAX_SKILL_NAME, pattern=SKILL_NAME)
    description: Stored = Field(min_length=1, max_length=MAX_DESCRIPTION)
    body: Stored = Field(min_length=1, max_length=MAX_BODY)
    gates: tuple[AgentPlaybookGate, ...] = ()


class AgentPlaybook(Identifiable, Created):
    """One published version of an agent playbook. A version is written once; a
    change is the next version. `findings` is what the lever checks read
    in it as it was published: advice for the person who published it,
    never a refusal. It is None on a version the checks never read, one
    published before they ran, which is not one they read and found
    nothing in."""

    name: Stored = Field(min_length=1, max_length=MAX_SKILL_NAME, pattern=SKILL_NAME)
    version: int = Field(ge=1)
    description: Stored = Field(min_length=1, max_length=MAX_DESCRIPTION)
    body: Stored = Field(min_length=1, max_length=MAX_BODY)
    gates: tuple[AgentPlaybookGate, ...] = ()
    published_by: UUID
    findings: tuple[LeverFinding, ...] | None = None


class AgentPlaybookInvocation(Identifiable, Created):
    """An agent playbook version brought into a session. Its gates hold in that
    session from then on. `pinned` marks the kind manual the session was made
    with, its kind's pin, whose text is the session's standing text; every
    other invocation's brief arrived as its invoker's message."""

    session_id: UUID
    agent_playbook_id: UUID
    name: Stored = Field(min_length=1, max_length=MAX_NAME)
    version: int = Field(ge=1)
    invoked_by: UUID
    pinned: bool = False


class AgentPlaybookPin(Identifiable, Trackable):
    """A version a tenant pinned to a kind as its kind manual, for the tenant's
    every session of the kind, or, with `project_id`, for those of one
    project, where it wins over the tenant's. Each new session it reaches
    pins the version's brief as its standing text and its gates into its
    policy. One pin a kind and a project; pinned again, it names the
    version then latest, and a session made before keeps its own."""

    kind: str = Field(min_length=1, max_length=MAX_KIND)
    project_id: UUID | None = None
    agent_playbook_id: UUID
    name: Stored = Field(min_length=1, max_length=MAX_SKILL_NAME, pattern=SKILL_NAME)
    version: int = Field(ge=1)
