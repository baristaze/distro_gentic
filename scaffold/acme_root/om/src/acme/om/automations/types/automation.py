"""An automation: a trigger that leads to an action, run as its creator or
as the tenant's automation principal, inside limits of its own. And a
run: the record of one firing, whatever became of it."""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import ClassVar, Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.agents.types.request import MAX_TITLE
from acme.om.attribution.types.principal import MAX_KIND
from acme.om.base import Created, Identifiable, Platform, Trackable
from acme.om.context import Role
from acme.om.steps.types.content import MAX_NAME, Stored

MAX_BRIEF = 20_000

MIN_EVERY = timedelta(minutes=1)
"""The shortest period a schedule fires at."""


class TriggerKind(StrEnum):
    EVENT = "event"  # an event the router placed, matched by its filters
    SCHEDULE = "schedule"  # a time, every `every`


class Trigger(Platform):
    """What fires an automation: an event that passes every filter it sets,
    or a schedule, at most once a `MIN_EVERY`. A filter left empty matches
    any event."""

    kind: TriggerKind
    integrations: tuple[Stored, ...] = ()
    arrivals: tuple[Stored, ...] = ()  # the arrival kinds of `intake`
    effects: tuple[Stored, ...] = ()  # the routing table's effects
    every: timedelta | None = None

    @model_validator(mode="after")
    def _a_schedule_has_a_period(self) -> Self:
        scheduled = self.kind is TriggerKind.SCHEDULE
        if scheduled != (self.every is not None):
            raise ValueError("a schedule fires every so often, and an event trigger does not")
        if self.every is not None and self.every < MIN_EVERY:
            raise ValueError(f"a schedule fires at most once every {MIN_EVERY}")
        if scheduled and (self.integrations or self.arrivals or self.effects):
            raise ValueError("a schedule has no event to filter")
        return self


class ActionKind(StrEnum):
    START_SESSION = "start_session"
    MESSAGE_SESSION = "message_session"  # a standing session, such as a CI triage one


class Action(Platform):
    """What a firing does: start a session of `agent_kind` with the brief, or
    send the brief to a standing session. The brief is the creator's word;
    the event that fired it reaches the session beside it, as data."""

    kind: ActionKind
    brief: Stored = Field(min_length=1, max_length=MAX_BRIEF)
    agent_kind: Stored | None = Field(default=None, min_length=1, max_length=MAX_KIND)
    title: Stored | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    session_id: UUID | None = None

    @model_validator(mode="after")
    def _names_what_it_acts_on(self) -> Self:
        starts = self.kind is ActionKind.START_SESSION
        if starts != (self.agent_kind is not None and self.title is not None):
            raise ValueError("a start names its agent kind and title, and a message does not")
        if starts == (self.session_id is not None):
            raise ValueError("a message names its standing session, and a start does not")
        return self


class Limits(Platform):
    """An automation's own bounds. `cost_cap_micros` is the most its runs may
    spend in one `period`, at list price; each run it starts is held to
    `run_cap_micros` of it by a budget on the run's tree. `rate` is the most
    firings in one `period`, `concurrency` the most runs at work at once,
    and `hop_limit` the longest chain of automations a firing may extend.
    A firing a rate or a concurrency stops is queued when `queue` says so."""

    cost_cap_micros: int = Field(gt=0)
    run_cap_micros: int = Field(gt=0)
    period: timedelta = Field(default=timedelta(days=1), gt=timedelta(0))
    rate: int = Field(gt=0)
    concurrency: int = Field(gt=0)
    queue: bool = False
    hop_limit: int = Field(default=3, ge=1)

    @model_validator(mode="after")
    def _a_run_within_the_cap(self) -> Self:
        if self.run_cap_micros > self.cost_cap_micros:
            raise ValueError("one run's cap is within the automation's")
        return self


class RunsAs(StrEnum):
    """Whose authority an automation's action runs on."""

    CREATOR = "creator"  # the person who made it, as their place stands at the firing
    AUTOMATION_PRINCIPAL = "automation_principal"  # the tenant's granted service principal


class AutomationPrincipal(Identifiable, Created):
    """The tenant's automation principal: a service principal the tenant
    grants, one a tenant, holding one role. `id` is the principal's, which
    the sessions it starts and the calls they make name. An automation that
    runs as it holds that role's authority and no more: never its
    creator's, and never the service role's."""

    role: Role
    granted_by: UUID


class Automation(Identifiable, Trackable):
    """A trigger, an action, and limits. It runs as its creator, whose live
    place in the tenant is read at every firing, or as the tenant's
    automation principal (`runs_as`), whose grant is read at every firing.
    `own_events` lets it fire on the events its own sessions caused, which
    it otherwise ignores."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = ("created_by", "updated_by")

    name: Stored = Field(min_length=1, max_length=MAX_NAME)
    trigger: Trigger
    action: Action
    limits: Limits
    runs_as: RunsAs = RunsAs.CREATOR
    own_events: bool = False
    enabled: bool = True


class RunStatus(StrEnum):
    STARTED = "started"  # its action ran
    QUEUED = "queued"  # a limit stopped it, and it waits its turn
    REFUSED = "refused"  # it never runs


class Refusal(StrEnum):
    """Why a firing did not run."""

    OWN_EVENT = "own_event"  # an event its own session caused
    HOP_LIMIT = "hop_limit"
    COST_CAP = "cost_cap"
    RATE = "rate"
    CONCURRENCY = "concurrency"
    PRINCIPAL = "principal"  # its creator holds no place now, or no automation principal is granted
    ACTION = "action"  # its action was refused: an unknown kind, a session gone
    UNATTRIBUTED = "unattributed"  # the platform's own act, with no session recorded for it


class AutomationRun(Identifiable, Created):
    """One firing, recorded whatever became of it. `hop` is its place in a
    chain: one for a firing on a person's event or a schedule, one more
    than the run whose session caused the event otherwise. `session_id` is
    the session it started or messaged; `budget_id` holds a started tree
    to `reserved_micros`, its share of the cost cap. A run counts against
    its limits from `started_at`. `event_text` is the event as the session
    will read it, kept only until the run starts or is refused: the
    session's own history keeps it from then on."""

    automation_id: UUID
    event_id: UUID | None = None
    caused_by: UUID | None = None  # the session whose act the event was
    status: RunStatus
    refusal: Refusal | None = None
    hop: int = Field(ge=1)
    session_id: UUID | None = None
    opened: bool = False  # it started `session_id`, rather than messaged it
    budget_id: UUID | None = None
    reserved_micros: int = Field(default=0, ge=0)
    event_text: Stored = Field(default="", max_length=MAX_BRIEF)
    started_at: datetime | None = None
    closed_at: datetime | None = None

    @model_validator(mode="after")
    def _a_stop_says_why(self) -> Self:
        if (self.status is RunStatus.STARTED) == (self.refusal is not None):
            raise ValueError("a refused or a queued run says why, and a started one does not")
        return self


class Firing(Platform):
    """What fires an automation, as the router placed it: the event, the
    routing table's effect, the session whose recorded act it is or follows
    from, whether the platform's account wrote it, and its text
    as the agent reads it, which reaches a started session as data. A
    schedule's firing names no event."""

    event_id: UUID | None = None
    occurred_at: datetime | None = None
    integration: Stored | None = None
    arrival: Stored | None = None
    effect: Stored | None = None
    caused_by: UUID | None = None
    platform: bool = False  # the platform's account wrote the event
    text: Stored = Field(default="", max_length=MAX_BRIEF)

    @model_validator(mode="after")
    def _an_event_has_a_time(self) -> Self:
        if (self.event_id is None) != (self.occurred_at is None):
            raise ValueError(
                "an event's firing says when the event occurred, and a schedule's does not"
            )
        return self


class Tally(Platform):
    """What an automation's runs hold when a firing asks to run: how many
    started in the period, what the runs of the period and the runs still
    at work reserve of the cap, and how many are at work."""

    started: int = Field(ge=0)
    reserved_micros: int = Field(ge=0)
    at_work: int = Field(ge=0)
