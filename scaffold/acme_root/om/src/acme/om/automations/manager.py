"""The automations swimlane: events turned into bounded work. A trigger, an
event with filters or a schedule, leads to an action: start a session, or
message a standing one. An automation runs as its creator, inside limits
of its own: a cost cap, a rate, a concurrency, and whether to queue when
limited. It ignores the events its own sessions caused unless it declares
otherwise, and a chain of automations stops at a hop limit. Every firing
is a recorded run."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.automations.types.automation import Automation, AutomationRun, Firing
from acme.om.context import TenantContext


class AutomationsManagerInterface(ABC):
    @abstractmethod
    async def create_automation(self, ctx: TenantContext, automation: Automation) -> Automation:
        """The create, announced, by a person in person: a context an
        agent's call runs under is `NotAuthorized`, so no agent sets work
        going for itself. Its creator is the caller, whom it runs as. An id
        written already answers the automation as stored."""
        ...

    @abstractmethod
    async def get_automation(self, ctx: TenantContext, automation_id: UUID) -> Automation:
        """An automation of the tenant; one another tenant holds is
        `NotFound`."""
        ...

    @abstractmethod
    async def get_runs(
        self, ctx: TenantContext, automation_id: UUID, limit: int
    ) -> tuple[AutomationRun, ...]:
        """Its runs, newest first; `limit` is clamped."""
        ...

    @abstractmethod
    async def fire(self, ctx: TenantContext, firing: Firing) -> tuple[AutomationRun, ...]:
        """Fires every enabled automation of the tenant whose trigger the
        event matches, under the tenant's service context, and answers a
        run for each, recorded whatever became of it. Each first takes up
        its queued runs, while its limits let them start. A firing runs
        once: the same event fires an automation into the one run it made."""
        ...

    @abstractmethod
    async def tick(self, ctx: TenantContext) -> tuple[AutomationRun, ...]:
        """Fires the tenant's schedules that are due, and takes up every
        automation's queued runs while its limits let them start; answers
        the runs it made or moved."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its automations
        and their runs, a batch at most a call. Any other tenant returns 0."""
        ...
