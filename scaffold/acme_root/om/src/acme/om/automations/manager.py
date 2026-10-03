"""The automations swimlane: events turned into bounded work. A trigger, an
event with filters or a schedule, leads to an action: start a session in
a project of the tenant, or message a standing one. An automation runs as its creator or as the
tenant's automation principal, inside limits of its own: a cost cap, a rate, a concurrency, and whether to queue when
limited. It ignores the events its own sessions caused unless it declares
otherwise, and a chain of automations stops at a hop limit. Every firing
is a recorded run."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.automations.types.automation import (
    Automation,
    AutomationPrincipal,
    AutomationRun,
    Firing,
)
from acme.om.context import Role, TenantContext


class AutomationsManagerInterface(ABC):
    @abstractmethod
    async def create_automation(self, ctx: TenantContext, automation: Automation) -> Automation:
        """The create, announced, by a person in person: a context an
        agent's call runs under is `NotAuthorized`, so no agent sets work
        going for itself. Its creator is the caller, whom it runs as. One
        that runs as the automation principal is `NotAuthorized` before a
        principal is granted, and to a caller whose role is below the
        grant. A start's project is the tenant's: another tenant's is
        `NotFound`, as one that never existed is. Where a session starts in
        a project (every stack but a local one), a start that names none is
        `ValidationFailed`, and one stored with none is refused at each
        firing, starting nothing. An id written already answers the
        automation as stored."""
        ...

    @abstractmethod
    async def update_automation(
        self, ctx: TenantContext, automation_id: UUID, automation: Automation
    ) -> Automation:
        """The tenant's automation as edited, announced, by a person in person,
        held to the create's checks: its trigger, its action, its limits,
        whom it runs as, and whether it is enabled all change; its id, its
        creator, and its creation stay. One that runs as its creator after the
        edit is edited by its creator alone, since its brief is the creator's
        word and it runs on the creator's authority: anyone else is
        `NotAuthorized`. Another tenant's is `NotFound`."""
        ...

    @abstractmethod
    async def list_automations(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> tuple[Automation, ...]:
        """The tenant's automations by id, strictly after `after`; `limit` is
        clamped."""
        ...

    @abstractmethod
    async def grant_principal(self, ctx: TenantContext, role: Role) -> AutomationPrincipal:
        """The tenant's automation principal granted `role`, by a person who
        manages its members, in person: a context an agent's call runs under
        is `NotAuthorized`, and so is a role above the granter's own or the
        service role. One a tenant: a grant over a standing one changes its
        role and keeps its id, and the next firing reads the new role."""
        ...

    @abstractmethod
    async def get_principal(self, ctx: TenantContext) -> AutomationPrincipal:
        """The tenant's automation principal; `NotFound` when none is granted."""
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
        """Fires each of the tenant's schedules once for the slot it is in, and
        takes up every automation's queued runs while its limits let them
        start; answers the runs it made or moved. A slot's run takes an id
        derived from the automation and the slot, so the ticks of several
        workers in one slot make one run, and a slot fired already fires
        nothing. An automation that fails is logged and passed by, and the
        others still fire."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its automations
        and their runs, a batch at most a call. Any other tenant returns 0."""
        ...
