from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.request import Start
from acme.om.attribution import PrincipalContext
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.automations.manager import AutomationsManagerInterface
from acme.om.automations.rules import due, hop_after, ignored, matches, period_start
from acme.om.automations.storage import AutomationStorageInterface
from acme.om.automations.types.automation import (
    ActionKind,
    Automation,
    AutomationRun,
    Firing,
    Refusal,
    RunStatus,
    TriggerKind,
)
from acme.om.base import Platform, derived_id, new_id, utcnow
from acme.om.budgets import BudgetsManagerInterface
from acme.om.budgets.types.budget import Budget, BudgetScopeKind, WindowKind
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import NotAuthorized, NotFound, PlatformException
from acme.om.intake.rules import in_person
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import versioned_row
from acme.om.steps.rules import message_step
from acme.om.steps.types.content import Content, TextBlock
from acme.om.steps.types.header import InputHeader
from acme.om.steps.types.step import Actor, Origin, Step, StepType
from acme.om.tenancy import TenancyManagerInterface

CREATED = "automations.automation.created"


class AutomationsOptions(Platform):
    # The most automations one firing reads a page, and runs one read takes.
    page: int = Field(default=200, gt=0)
    # A started run that names no session after this was lost before its
    # action ran: it is closed, and its reservation goes with its period.
    lost_after: timedelta = timedelta(minutes=5)
    max_page: int = Field(default=200, gt=0)
    purge_batch: int = Field(default=1000, gt=0)


class AutomationsManagerImpl(AutomationsManagerInterface):
    def __init__(
        self,
        storage: AutomationStorageInterface,
        agents: AgentsManagerInterface,
        sessions: AgentSessionsManagerInterface,
        budgets: BudgetsManagerInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        principal_context: PrincipalContext,
        options: AutomationsOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._agents = agents
        self._sessions = sessions
        self._budgets = budgets
        self._tenancy = tenancy
        self._relay = relay
        self._live = principal_context
        self._options = options
        self._clock = clock

    async def create_automation(self, ctx: TenantContext, automation: Automation) -> Automation:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("an automation is made by a person, never by an agent's call")
        now = self._clock()
        made = Automation.model_validate(
            {
                **automation.model_dump(),
                "created_at": now,
                "updated_at": now,
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
            }
        )
        rows = (versioned_row(ctx, CREATED, made.id, 1),)
        if await self._storage.create_automation(ctx.org_id, made, rows):
            await self._relay.relay_all(ctx.org_id, rows)
        return await self.get_automation(ctx, made.id)

    async def get_automation(self, ctx: TenantContext, automation_id: UUID) -> Automation:
        ctx.require(Permission.READ)
        found = await self._storage.read_automation(ctx.org_id, automation_id)
        if found is None:
            raise NotFound(f"automation {automation_id} not found")
        return found

    async def get_runs(
        self, ctx: TenantContext, automation_id: UUID, limit: int
    ) -> tuple[AutomationRun, ...]:
        ctx.require(Permission.READ)
        bounded = max(1, min(limit, self._options.max_page))
        return tuple(await self._storage.read_runs(ctx.org_id, automation_id, bounded))

    async def fire(self, ctx: TenantContext, firing: Firing) -> tuple[AutomationRun, ...]:
        ctx.require(Permission.WRITE)
        cause = None
        if firing.caused_by is not None:
            cause = await self._storage.read_session_run(ctx.org_id, firing.caused_by)
        runs: list[AutomationRun] = []
        for automation in await self._enabled(ctx):
            if not matches(automation.trigger, firing):
                continue
            runs.extend(await self._drain(ctx, automation))
            runs.append(await self._fire_one(ctx, automation, firing, cause))
        return tuple(runs)

    async def tick(self, ctx: TenantContext) -> tuple[AutomationRun, ...]:
        ctx.require(Permission.WRITE)
        now = self._clock()
        runs: list[AutomationRun] = []
        for automation in await self._enabled(ctx):
            runs.extend(await self._drain(ctx, automation))
            if automation.trigger.kind is not TriggerKind.SCHEDULE:
                continue
            latest = await self._storage.read_runs(ctx.org_id, automation.id, 1)
            if due(automation.trigger, latest[0].created_at if latest else None, now):
                runs.append(await self._fire_one(ctx, automation, Firing(), None))
        return tuple(runs)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    # A firing.

    async def _fire_one(
        self,
        ctx: TenantContext,
        automation: Automation,
        firing: Firing,
        cause: AutomationRun | None,
    ) -> AutomationRun:
        now = self._clock()
        # One run an event: a redelivered event finds the run it made.
        run_id = new_id()
        if firing.event_id is not None and firing.occurred_at is not None:
            run_id = derived_id(firing.event_id, firing.occurred_at, f"automation:{automation.id}")
        run = AutomationRun(
            id=run_id,
            created_at=now,
            automation_id=automation.id,
            event_id=firing.event_id,
            caused_by=firing.caused_by,
            status=RunStatus.REFUSED,
            refusal=Refusal.HOP_LIMIT,
            hop=hop_after(cause),
            event_text=firing.text,
        )
        stop = ignored(automation, cause)
        if stop is not None:
            return await self._storage.create_run(
                ctx.org_id, run.model_copy(update={"refusal": stop})
            )
        return await self._admit(ctx, automation, run)

    async def _admit(
        self, ctx: TenantContext, automation: Automation, run: AutomationRun
    ) -> AutomationRun:
        """Asks the limits, and runs the action of a run they start."""
        creator = await self._creator(ctx, automation)
        if creator is None:
            refused = run.model_copy(
                update={"status": RunStatus.REFUSED, "refusal": Refusal.PRINCIPAL}
            )
            if run.status is RunStatus.QUEUED:
                await self._storage.write_run(ctx.org_id, refused)
                return refused
            return await self._storage.create_run(ctx.org_id, refused)
        await self._close_finished(ctx, automation)
        since = period_start(automation.limits, self._clock())
        landed = await self._storage.admit(ctx.org_id, run, automation.limits, since)
        if landed.status is not RunStatus.STARTED or landed.session_id is not None:
            return landed
        try:
            return await self._act(ctx, creator, automation, landed)
        except PlatformException:
            # An action the engine refuses never runs: the run says so, and
            # its share of the cap goes back.
            refused = landed.model_copy(
                update={
                    "status": RunStatus.REFUSED,
                    "refusal": Refusal.ACTION,
                    "reserved_micros": 0,
                    "closed_at": self._clock(),
                }
            )
            await self._storage.write_run(ctx.org_id, refused)
            return refused

    async def _act(
        self,
        ctx: TenantContext,
        creator: TenantContext,
        automation: Automation,
        run: AutomationRun,
    ) -> AutomationRun:
        """The action of a started run, as its creator. A started session is
        held to the run's reservation by a budget on its tree before anything
        wakes it; the event reaches it as data, and the brief as the
        creator's message."""
        action = automation.action
        opened = action.kind is ActionKind.START_SESSION
        if opened:
            assert action.agent_kind is not None and action.title is not None
            session = await self._agents.start_session(
                creator,
                Start(
                    id=derived_id(run.id, run.created_at, "session"),
                    kind=action.agent_kind,
                    title=action.title,
                ),
            )
            budget = Budget(
                id=derived_id(run.id, run.created_at, "budget"),
                created_at=run.created_at,
                updated_at=run.created_at,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                scope_kind=BudgetScopeKind.TREE,
                scope_key=str(session.root_id),
                window_kind=WindowKind.LIFE,
                cost_micros=run.reserved_micros,
            )
            await self._budgets.create_budget(ctx, budget)
            session_id, budget_id = session.id, budget.id
        else:
            assert action.session_id is not None
            session_id, budget_id = action.session_id, None
        acted = run.model_copy(
            update={"session_id": session_id, "opened": opened, "budget_id": budget_id}
        )
        await self._storage.write_run(ctx.org_id, acted)
        inputs: list[Step] = []
        if run.event_text:
            inputs.append(self._event_step(ctx, run, session_id))
        brief = message_step(
            derived_id(run.id, run.created_at, "brief"),
            self._clock(),
            session_id,
            creator,
            action.brief,
        )
        inputs.append(brief)
        await self._sessions.receive(creator, session_id, inputs)
        return acted

    def _event_step(self, ctx: TenantContext, run: AutomationRun, session_id: UUID) -> Step:
        """The event that fired a run, as data: it never waits to wake the
        session, since the brief that follows it does."""
        step_id = derived_id(run.id, run.created_at, "event")
        return Step(
            id=step_id,
            created_at=self._clock(),
            session_id=session_id,
            loop_id=step_id,
            type=StepType.EVENT,
            actor=Actor.EXTERNAL,
            origin=Origin.AUTOMATION,
            header=InputHeader(
                waking=False, principal=Principal(kind=PrincipalKind.SERVICE, id=ctx.user_id)
            ),
            content=Content(blocks=(TextBlock(text=run.event_text),)),
        )

    async def _drain(self, ctx: TenantContext, automation: Automation) -> list[AutomationRun]:
        """Its queued runs, oldest first, while its limits start them."""
        moved: list[AutomationRun] = []
        queued = await self._storage.read_queued_runs(ctx.org_id, automation.id, self._options.page)
        for run in queued:
            landed = await self._admit(ctx, automation, run)
            if landed.status is RunStatus.QUEUED:
                break
            moved.append(landed)
        return moved

    async def _close_finished(self, ctx: TenantContext, automation: Automation) -> None:
        """Closes the runs whose sessions are no longer at work, so the
        concurrency counts the ones that are."""
        now = self._clock()
        for run in await self._storage.read_open_runs(
            ctx.org_id, automation.id, self._options.page
        ):
            if run.session_id is None:
                done = now - run.created_at >= self._options.lost_after
            else:
                try:
                    session = await self._sessions.get_session(ctx, run.session_id)
                    done = session.status is SessionStatus.IDLE
                except NotFound:
                    done = True
            if done:
                await self._storage.write_run(ctx.org_id, run.model_copy(update={"closed_at": now}))

    async def _creator(self, ctx: TenantContext, automation: Automation) -> TenantContext | None:
        """The creator's live context, read at the firing: none when they hold
        no place in the tenant now."""
        try:
            return await self._live(
                ctx, ctx.org_id, Principal(kind=PrincipalKind.PERSON, id=automation.created_by)
            )
        except NotAuthorized:
            return None

    async def _enabled(self, ctx: TenantContext) -> list[Automation]:
        found: list[Automation] = []
        after: UUID | None = None
        while True:
            page = await self._storage.read_automations(ctx.org_id, after, self._options.page)
            found.extend(a for a in page if a.enabled)
            if len(page) < self._options.page:
                return found
            after = page[-1].id
