"""Wire types of a tenant's playbooks: a version as published, and the next
one a person publishes, with its gates."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.playbooks.types.playbook import MAX_BODY, MAX_DESCRIPTION, MAX_SKILL_NAME, SKILL_NAME
from acme.om.tools.types.policy import Decision
from acme.om.tools.types.tool import CLASS_NAME, TOOL_NAME
from acme.services.api.types.common import RequestBody, View

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
    id: UUID
    name: str
    version: int
    description: str
    body: str
    gates: list[GateView]
    published_by: UUID
    created_at: datetime
