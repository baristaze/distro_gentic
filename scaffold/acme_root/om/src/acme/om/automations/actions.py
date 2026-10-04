"""A product's own kinds of automation action, as a registry. The platform's
two actions start a session or message one; a product adds an action that
does its own work in the firing, a check that says when the run it
started ended, so the run closes on that end rather than as lost, and a
check of the person who writes the automation, so one its firings would
refuse is refused when it is written. Each
root builds the one registry from what the product hands it
(`root.ProductKinds.actions`), and a name the platform's actions hold, or
one registered twice, is refused at boot."""

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from uuid import UUID

from acme.om.automations.types.automation import (
    ACTION_NAME,
    PLATFORM_ACTIONS,
    AutomationRun,
    RunOutcome,
)
from acme.om.base import Platform
from acme.om.context import TenantContext


class AutomationActionInterface(ABC):
    """One kind of action a product adds. `name` is what an automation's
    action names as its kind; `params` is the shape its params are held to
    when a person writes the automation."""

    name: str
    params: type[Platform]

    @abstractmethod
    async def act(self, ctx: TenantContext, run: AutomationRun, params: Platform) -> UUID:
        """Does the action of a started run, as the automation runs, under
        `ctx`: its creator's or its principal's live context. `run` carries
        the event that fired it in `event_text`, as data. Answers the id of
        the work it started, which the run keeps and `ended` reads. A run
        lost before it records that id is acted on again, so the work takes
        an id derived from the run's and lands once. A `PlatformException`
        refuses the run, and its share of the cap goes back."""
        ...

    @abstractmethod
    async def ended(self, ctx: TenantContext, run: AutomationRun) -> RunOutcome | None:
        """How the work `run.work_id` names ended, under the tenant's service
        context: None while it is at work, so the run stays open and counts
        in the concurrency."""
        ...

    @abstractmethod
    async def check_writer(self, ctx: TenantContext, params: Platform) -> None:
        """Refuses the person writing an enabled automation of this kind,
        under `ctx`, their own context in person, with `params` already held
        to the kind's shape. A writer it refuses is told when the automation
        is written, not by a refused run at each firing: it raises
        `NotAuthorized` with the reason, which the create or the edit answers
        as is, and any other `PlatformException` answers as itself. A kind
        with no rule of its own returns, and admits every writer the platform
        admits. A disabled automation is never asked about, so its writer can
        always turn it off. The firing still runs `act` under the run's live
        context, which refuses what changed since."""
        ...


class AutomationActions:
    """The product's action kinds a process knows, each once. A name the
    platform's actions hold is refused, so a product never takes one of
    them over, and so is a name registered twice."""

    def __init__(self, actions: Iterable[AutomationActionInterface]) -> None:
        found: dict[str, AutomationActionInterface] = {}
        for action in actions:
            if not re.match(ACTION_NAME, action.name):
                raise ValueError(f"an action kind is named in lower case, never {action.name!r}")
            if action.name in PLATFORM_ACTIONS:
                raise ValueError(f"{action.name} is the platform's action, never a product's")
            if action.name in found:
                raise ValueError(f"action kind {action.name} is registered twice")
            found[action.name] = action
        self._actions: Mapping[str, AutomationActionInterface] = MappingProxyType(found)

    def get(self, name: str) -> AutomationActionInterface | None:
        """The product's kind of that name; None for one no product declares."""
        return self._actions.get(name)
