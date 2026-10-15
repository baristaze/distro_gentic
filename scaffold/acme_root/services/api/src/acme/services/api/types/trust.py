"""Wire types of trust: a tenant's own keys to its model providers, written
and never read back, and a session's shape as an operator reads it."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, SecretStr

from acme.om.agent_steps.types.agent_step import Actor, AgentStepType, Origin
from acme.om.agent_steps.types.content import ContentState
from acme.om.agent_steps.types.header import ControlCommand, LoopOutcome, ToolFailure
from acme.om.trust.types.provider_key import KeyStatus
from acme.services.api.types.agent_sessions import ParkView
from acme.services.api.types.common import RequestBody, View
from acme.services.api.types.matrix import ProviderName

MAX_KEY = 4096
"""The longest key value a provider issues, with room to spare."""


class SaveKeyRequest(RequestBody):
    """A key's value. It is written once, under a new reference, and no
    response, log, or error ever carries it."""

    value: SecretStr = Field(min_length=1, max_length=MAX_KEY)


class ProviderKeyView(View):
    """What the tenant sees of a key: its reference, who added it and when,
    its state, and when it was last used. Never its value."""

    id: UUID
    provider: ProviderName
    status: KeyStatus
    created_at: datetime
    created_by: UUID
    last_used_at: datetime | None


class StepShapeView(View):
    """One step as an operator's `read` sees it: what it is, who wrote it,
    and the fields of its header a reader acts on, never what it says.
    `content` says whether what it says is kept."""

    id: UUID
    seq: int
    loop_id: UUID
    type: AgentStepType
    actor: Actor
    origin: Origin
    responds_to: UUID | None
    created_at: datetime
    content: ContentState
    tool: str | None
    failure: ToolFailure | None
    command: ControlCommand | None
    park: ParkView | None
    outcome: LoopOutcome | None


class ShapePageView(View):
    """One page of a session's shape, after the seq the request named."""

    items: list[StepShapeView]
    has_more: bool
