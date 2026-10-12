"""Wire types of a tenant's playbooks: a version as published, and the next
one a person publishes, with its gates; an invocation of one into a
session; and a pin of one to a kind as its manual."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.attribution.types.principal import MAX_KIND
from acme.om.playbooks.types.playbook import MAX_BODY, MAX_DESCRIPTION, MAX_SKILL_NAME, SKILL_NAME
from acme.om.tools.types.policy import Decision
from acme.om.tools.types.tool import CLASS_NAME, TOOL_NAME
from acme.services.api.types.common import RequestBody, View
from acme.services.api.types.levers import FindingView

MAX_GATES = 50


class GateBody(RequestBody):
    """The calls a gate selects, by tool or by class, and what they need: a
    person's approval, or a denial. A gate never allows."""

    tool: str | None = Field(default=None, pattern=TOOL_NAME)
    authorization_class: str | None = Field(default=None, pattern=CLASS_NAME)
    decision: Decision


class GateView(View):
    tool: str | None
    authorization_class: str | None
    decision: Decision


class PublishRequest(RequestBody):
    """The next version of a playbook's name: its description, its body, and
    its gates."""

    name: str = Field(min_length=1, max_length=MAX_SKILL_NAME, pattern=SKILL_NAME)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION)
    body: str = Field(min_length=1, max_length=MAX_BODY)
    gates: list[GateBody] = Field(default_factory=list[GateBody], max_length=MAX_GATES)


class PlaybookView(View):
    """A version as published, with what the lever checks found in it as it
    was: advice, which never refused the publish. `findings` is null on a
    version the checks never read, one published before they ran, and an
    empty list on one they read and found nothing in."""

    id: UUID
    name: str
    version: int
    description: str
    body: str
    gates: list[GateView]
    published_by: UUID
    created_at: datetime
    findings: list[FindingView] | None


class InvokeRequest(RequestBody):
    """The session a person brings the name's latest version into, one they
    may instruct."""

    session_id: UUID


class InvocationView(View):
    """A version brought into a session. `pinned` marks the manual the
    session was made with, whose brief is its standing text; every other
    invocation's brief arrived as its invoker's message."""

    id: UUID
    session_id: UUID
    playbook_id: UUID
    name: str
    version: int
    invoked_by: UUID
    pinned: bool
    created_at: datetime


class PinRequest(RequestBody):
    """A kind's manual: the name whose latest version is pinned to `kind`,
    for the tenant's sessions of it, or with `project_id` those of one
    project, where it wins over the tenant's."""

    kind: str = Field(min_length=1, max_length=MAX_KIND)
    name: str = Field(min_length=1, max_length=MAX_SKILL_NAME, pattern=SKILL_NAME)
    project_id: UUID | None = None


class PinView(View):
    """A version pinned to a kind as its manual. Each session of the kind
    made after it was pinned holds it; one made before keeps its own."""

    id: UUID
    kind: str
    project_id: UUID | None
    playbook_id: UUID
    name: str
    version: int
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    updated_by: UUID
