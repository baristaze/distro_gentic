"""Wire types of a tenant's automations: an automation a person makes or
edits, with its trigger, its action, and its limits; the automation as
stored; and the tenant's automation principal, the role a person grants it
and the grant as it stands."""

from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field, JsonValue

from acme.om.agents.types.request import MAX_TITLE
from acme.om.attribution.types.principal import MAX_KIND
from acme.om.automations.types.automation import ACTION_NAME, MAX_BRIEF, RunsAs, TriggerKind
from acme.om.context import Role
from acme.om.steps.types.content import MAX_NAME
from acme.services.api.types.common import RequestBody, View

MAX_FILTER = 50
"""The most values one of a trigger's filters names."""

Filter = list[str]


class TriggerBody(RequestBody):
    """An event that passes every filter set (one left empty matches any),
    or a schedule, every `every` seconds, a minute at least."""

    kind: TriggerKind
    integrations: Filter = Field(default_factory=list[str], max_length=MAX_FILTER)
    arrivals: Filter = Field(default_factory=list[str], max_length=MAX_FILTER)
    effects: Filter = Field(default_factory=list[str], max_length=MAX_FILTER)
    every: timedelta | None = None


class TriggerView(View):
    kind: TriggerKind
    integrations: list[str]
    arrivals: list[str]
    effects: list[str]
    every: timedelta | None


class ActionBody(RequestBody):
    """`start_session`: start a session of `agent_kind` titled `title` in the
    tenant's project `project_id`. `message_session`: send the brief to the
    standing session `session_id`. The brief is the creator's word. Any
    other kind is one the product declares, which takes its `params` and no
    brief; a kind no product declares is refused."""

    kind: str = Field(pattern=ACTION_NAME)
    brief: str | None = Field(default=None, min_length=1, max_length=MAX_BRIEF)
    agent_kind: str | None = Field(default=None, min_length=1, max_length=MAX_KIND)
    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    project_id: UUID | None = None
    session_id: UUID | None = None
    params: dict[str, JsonValue] = Field(default_factory=lambda: {})


class ActionView(View):
    kind: str
    brief: str | None
    agent_kind: str | None
    title: str | None
    project_id: UUID | None
    session_id: UUID | None
    params: dict[str, JsonValue]


class LimitsBody(RequestBody):
    """The most its runs spend in a period, in millionths at list price, and
    the share one run may take; the most firings a period; the most runs at
    work at once; whether a stopped firing waits, and how many may; and the
    longest chain of automations a firing extends."""

    cost_cap_micros: int = Field(gt=0)
    run_cap_micros: int = Field(gt=0)
    period: timedelta | None = Field(default=None, gt=timedelta(0))  # a day when left out
    rate: int = Field(gt=0)
    concurrency: int = Field(gt=0)
    queue: bool = False
    queue_depth: int = Field(default=50, ge=1)
    hop_limit: int = Field(default=3, ge=1)


class LimitsView(View):
    cost_cap_micros: int
    run_cap_micros: int
    period: timedelta
    rate: int
    concurrency: int
    queue: bool
    queue_depth: int
    hop_limit: int


class AutomationRequest(RequestBody):
    """An automation whole, as made or as edited."""

    name: str = Field(min_length=1, max_length=MAX_NAME)
    trigger: TriggerBody
    action: ActionBody
    limits: LimitsBody
    runs_as: RunsAs | None = None  # its creator when left out
    own_events: bool = False
    enabled: bool = True


class AutomationView(View):
    """An automation, whom it runs as, and who made and last edited it."""

    id: UUID
    name: str
    trigger: TriggerView
    action: ActionView
    limits: LimitsView
    runs_as: RunsAs
    own_events: bool
    enabled: bool
    created_at: datetime
    created_by: UUID
    updated_at: datetime
    updated_by: UUID


class GrantRequest(RequestBody):
    """The role the automation principal holds: never above the granter's."""

    role: Role


class AutomationPrincipalView(View):
    """The tenant's automation principal: its id, the role it holds, and who
    granted it."""

    id: UUID
    role: Role
    granted_by: UUID
    created_at: datetime
