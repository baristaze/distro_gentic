import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field
from pydantic import ValidationError as ShapeError

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.request import Start
from acme.om.attribution import PrincipalContext
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.automations.actions import AutomationActionInterface, AutomationActions
from acme.om.automations.manager import AutomationsManagerInterface
from acme.om.automations.rules import hop_after, ignored, matches, slot
from acme.om.automations.storage import AutomationStorageInterface
from acme.om.automations.types.automation import (
    PLATFORM_ACTIONS,
    ActionKind,
    Automation,
    AutomationPrincipal,
    AutomationRun,
    Firing,
    Refusal,
    RunOutcome,
    RunsAs,
    RunStatus,
)
from acme.om.base import Platform, derived_id, new_id, utcnow
from acme.om.budgets import BudgetsManagerInterface
from acme.om.budgets.types.budget import Budget, BudgetScopeKind, WindowKind
from acme.om.context import Permission, Role, TenantContext
from acme.om.events import EventsManagerInterface
from acme.om.events.manager import audit_event
from acme.om.exceptions import NotAuthorized, NotFound, PlatformException, ValidationFailed
from acme.om.intake.rules import in_person
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import outbox_row, versioned_row
from acme.om.projects import ProjectsManagerInterface
from acme.om.steps.rules import message_step
from acme.om.steps.types.content import Content, TextBlock
from acme.om.steps.types.header import InputHeader
from acme.om.steps.types.step import Actor, Origin, Step, StepType
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tenancy.rules import role_at_most

log = logging.getLogger(__name__)

CREATED = "automations.automation.created"
UPDATED = "automations.automation.updated"
GRANTED = "automations.principal.granted"


class AutomationsOptions(Platform):
    # The most automations one firing reads a page, and runs one read takes.
    page: int = Field(default=200, gt=0)
    # A started run that names no session, and no work of a product's
    # action, after this was lost before its action ran: it is closed, and
    # its reservation goes with its period.
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
        events: EventsManagerInterface,
        projects: ProjectsManagerInterface,
        principal_context: PrincipalContext,
        options: AutomationsOptions,
        clock: Callable[[], datetime] = utcnow,
        *,
        project_required: bool,
        actions: AutomationActions | None = None,
    ) -> None:
        """`project_required` refuses a start that names no project: what
        every stack but a local one sets, so no per-project policy is
        skipped by a session an automation starts. `actions` are the
        product's own kinds of action; None declares none."""
        self._storage = storage
        self._agents = agents
        self._projects = projects
        self._project_required = project_required
        self._sessions = sessions
        self._budgets = budgets
        self._tenancy = tenancy
        self._relay = relay
        self._events = events
        self._live = principal_context
        self._options = options
        self._clock = clock
        self._actions = actions or AutomationActions(())

    async def create_automation(self, ctx: TenantContext, automation: Automation) -> Automation:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("an automation is made by a person, never by an agent's call")
        await self._check_principal(ctx, automation)
        self._check_kind(automation)
        await self._check_project(ctx, automation)
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

    async def update_automation(
        self, ctx: TenantContext, automation_id: UUID, automation: Automation
    ) -> Automation:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("an automation is edited by a person, never by an agent's call")
        stored = await self.get_automation(ctx, automation_id)
        if automation.runs_as is RunsAs.CREATOR and stored.created_by != ctx.user_id:
            raise NotAuthorized(
                "an automation that runs as its creator is edited by its creator alone"
            )
        await self._check_principal(ctx, automation)
        self._check_kind(automation)
        await self._check_project(ctx, automation)
        # The editor is its creator from here on: one that runs as its
        # creator is its creator's to edit, and one that runs as the
        # principal fires on its creator's role, which is the editor's that
        # `_check_principal` held to the grant.
        edited = Automation.model_validate(
            {
                **automation.model_dump(),
                "id": stored.id,
                "created_at": stored.created_at,
                "created_by": ctx.user_id,
                "updated_at": self._clock(),
                "updated_by": ctx.user_id,
            }
        )
        rows = (outbox_row(ctx, UPDATED, edited.id, {}),)
        if not await self._storage.write_automation(ctx.org_id, edited, rows):
            raise NotFound(f"automation {automation_id} not found")
        await self._relay.relay_all(ctx.org_id, rows)
        return edited

    async def list_automations(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> tuple[Automation, ...]:
        ctx.require(Permission.READ)
        limit = max(1, min(limit, self._options.max_page))
        return tuple(await self._storage.read_automations(ctx.org_id, after, limit))

    async def grant_principal(self, ctx: TenantContext, role: Role) -> AutomationPrincipal:
        ctx.require(Permission.MANAGE_MEMBERS)
        if not in_person(ctx):
            raise NotAuthorized("an automation principal is granted by a person, in person")
        if not role_at_most(role, ctx.role):
            raise NotAuthorized(f"a {ctx.role.value} grants no {role.value} principal")
        granted = await self._storage.write_principal(
            ctx.org_id,
            AutomationPrincipal(
                id=new_id(), created_at=self._clock(), role=role, granted_by=ctx.user_id
            ),
        )
        await self._audit(ctx, granted)
        return granted

    async def get_principal(self, ctx: TenantContext) -> AutomationPrincipal:
        ctx.require(Permission.READ)
        found = await self._storage.read_principal(ctx.org_id)
        if found is None:
            raise NotFound("no automation principal is granted")
        return found

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
            try:
                runs.extend(await self._tick_one(ctx, automation, now))
            except Exception:
                # One automation that fails never stops the tenant's others:
                # its queue and its slot are asked again at the next tick.
                log.exception("automation %s of org %s failed its tick", automation.id, ctx.org_id)
        return tuple(runs)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    # A firing.

    async def _tick_one(
        self, ctx: TenantContext, automation: Automation, now: datetime
    ) -> list[AutomationRun]:
        """Its queued runs as its limits start them, and its schedule's slot
        at `now` when no run holds it yet."""
        runs = await self._drain(ctx, automation)
        at = slot(automation.trigger, automation.created_at, now)
        if at is None:
            return runs
        run_id = derived_id(automation.id, at, "schedule")
        if await self._storage.read_run(ctx.org_id, run_id) is not None:
            return runs
        runs.append(await self._fire_one(ctx, automation, Firing(), None, run_id=run_id))
        return runs

    async def _fire_one(
        self,
        ctx: TenantContext,
        automation: Automation,
        firing: Firing,
        cause: AutomationRun | None,
        *,
        run_id: UUID | None = None,
    ) -> AutomationRun:
        now = self._clock()
        # One run an event, and one a schedule's slot: a redelivered event,
        # or another worker's tick in the slot, finds the run it made.
        run_id = run_id or new_id()
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
        stop = ignored(automation, firing, cause)
        if stop is not None:
            return await self._storage.create_run(
                ctx.org_id, run.model_copy(update={"refusal": stop, "event_text": ""})
            )
        return await self._admit(ctx, automation, run)

    async def _admit(
        self, ctx: TenantContext, automation: Automation, run: AutomationRun
    ) -> AutomationRun:
        """Asks the limits, and runs the action of a run they start. A start
        that names no project where one is required, and an automation whose
        principal cannot act, are refused before the limits hold anything."""
        if self._outside_projects(automation):
            # Saved before a project was required, or under a local stack:
            # its session would take no project's budget or policy.
            return await self._refuse(ctx, run, Refusal.PROJECT)
        if self._unknown_kind(automation):
            # Its product's kind left this process's registry since it was
            # saved: nothing would act on it.
            return await self._refuse(ctx, run, Refusal.ACTION)
        creator = await self._runs_as(ctx, automation)
        if creator is None:
            return await self._refuse(ctx, run, Refusal.PRINCIPAL)
        await self._close_finished(ctx, automation)
        landed = await self._storage.admit(ctx.org_id, run, automation.limits, self._clock())
        acted = landed.session_id is not None or landed.work_id is not None
        if landed.status is not RunStatus.STARTED or acted:
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
                    "event_text": "",
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
        creator's message. A product's action is its kind's to run."""
        action = automation.action
        kind = self._actions.get(action.kind)
        if kind is not None:
            return await self._act_product(ctx, creator, kind, automation, run)
        assert action.brief is not None  # a session's action carries one
        opened = action.kind == ActionKind.START_SESSION
        if opened:
            assert action.agent_kind is not None and action.title is not None
            start = Start(
                id=derived_id(run.id, run.created_at, "session"),
                kind=action.agent_kind,
                title=action.title,
            )
            # In its project from its first moment, so the project's budget
            # and policies hold every call it makes.
            session = (
                await self._agents.start_session(creator, start)
                if action.project_id is None
                else await self._projects.start_session(creator, action.project_id, start)
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
        # The session's history holds the event from here on, under its key;
        # the run keeps none of it. A run lost before this write is acted on
        # again, under the same ids, and lands nothing twice.
        acted = run.model_copy(
            update={
                "session_id": session_id,
                "opened": opened,
                "budget_id": budget_id,
                "event_text": "",
            }
        )
        await self._storage.write_run(ctx.org_id, acted)
        return acted

    async def _act_product(
        self,
        ctx: TenantContext,
        creator: TenantContext,
        kind: AutomationActionInterface,
        automation: Automation,
        run: AutomationRun,
    ) -> AutomationRun:
        """A product's action, run by its kind as the automation runs; the
        run keeps the id of the work it started, and is at work until the
        kind's check says that work ended."""
        try:
            params = kind.params.model_validate(automation.action.plain_params())
        except ShapeError as exc:
            # Saved under an earlier shape of its kind: refused, never acted on.
            raise ValidationFailed(f"the params of {kind.name} are malformed: {exc}") from exc
        work_id = await kind.act(creator, run, params)
        acted = run.model_copy(update={"work_id": work_id, "event_text": ""})
        await self._storage.write_run(ctx.org_id, acted)
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
        """Closes the runs whose sessions are no longer at work, and those
        whose product's work ended as its kind's check says, with the
        outcome it said, so the concurrency counts the ones that are."""
        now = self._clock()
        for run in await self._storage.read_open_runs(
            ctx.org_id, automation.id, self._options.page
        ):
            outcome: RunOutcome | None = None
            if run.work_id is not None:
                outcome = await self._ended(ctx, automation, run)
                done = outcome is not None
            elif run.session_id is None:
                done = now - run.created_at >= self._options.lost_after
            else:
                try:
                    session = await self._sessions.get_session(ctx, run.session_id)
                    done = session.status is SessionStatus.IDLE
                except NotFound:
                    done = True
            if done:
                closed = run.model_copy(
                    update={"closed_at": now, "event_text": "", "outcome": outcome}
                )
                await self._storage.write_run(ctx.org_id, closed)

    async def _ended(
        self, ctx: TenantContext, automation: Automation, run: AutomationRun
    ) -> RunOutcome | None:
        """How a product's work ended, as its kind's check says. A check
        that fails, or a kind this process no longer knows, leaves the run
        open: its work may still be at work, so it is never closed as
        lost, and the next firing asks again."""
        kind = self._actions.get(automation.action.kind)
        if kind is None:
            return None
        try:
            return await kind.ended(ctx, run)
        except Exception:
            log.exception("the check of run %s of org %s failed", run.id, ctx.org_id)
            return None

    async def _refuse(
        self, ctx: TenantContext, run: AutomationRun, refusal: Refusal
    ) -> AutomationRun:
        """The run refused before the limits were asked: it starts nothing
        and reserves nothing. A queued run is rewritten, and a new one made."""
        refused = run.model_copy(
            update={"status": RunStatus.REFUSED, "refusal": refusal, "event_text": ""}
        )
        if run.status is RunStatus.QUEUED:
            await self._storage.write_run(ctx.org_id, refused)
            return refused
        return await self._storage.create_run(ctx.org_id, refused)

    async def _check_principal(self, ctx: TenantContext, automation: Automation) -> None:
        """One that runs as the automation principal is made or edited only
        once a principal is granted, by a caller whose role is at least the
        grant."""
        if automation.runs_as is not RunsAs.AUTOMATION_PRINCIPAL:
            return
        granted = await self._storage.read_principal(ctx.org_id)
        if granted is None:
            raise NotAuthorized("an automation runs as no principal before one is granted")
        if not role_at_most(granted.role, ctx.role):
            raise NotAuthorized(
                f"a {ctx.role.value} makes no automation that runs as a {granted.role.value}"
            )

    def _check_kind(self, automation: Automation) -> None:
        """A product's action names a kind a product declares, and its params
        hold to that kind's shape: otherwise it is `ValidationFailed`, so no
        automation is written that could never act."""
        action = automation.action
        if action.kind in PLATFORM_ACTIONS:
            return
        kind = self._actions.get(action.kind)
        if kind is None:
            raise ValidationFailed(f"no product declares the action kind {action.kind}")
        try:
            kind.params.model_validate(action.plain_params())
        except ShapeError as exc:
            raise ValidationFailed(f"the params of {action.kind} are malformed: {exc}") from exc

    def _unknown_kind(self, automation: Automation) -> bool:
        kind = automation.action.kind
        return kind not in PLATFORM_ACTIONS and self._actions.get(kind) is None

    async def _check_project(self, ctx: TenantContext, automation: Automation) -> None:
        """A start's project is one of the caller's tenant: another tenant's
        is `NotFound`, as one that never existed is. One that names none is
        `ValidationFailed` where a session starts in a project."""
        project_id = automation.action.project_id
        if project_id is not None:
            await self._projects.get_project(ctx, project_id)
        elif self._outside_projects(automation):
            raise ValidationFailed(
                "an automation's session starts in a project: name its project_id"
            )

    def _outside_projects(self, automation: Automation) -> bool:
        """A start that names no project where a session starts in one."""
        action = automation.action
        return (
            self._project_required
            and action.kind == ActionKind.START_SESSION
            and action.project_id is None
        )

    async def _runs_as(self, ctx: TenantContext, automation: Automation) -> TenantContext | None:
        """The live context the automation's action runs under, read at the
        firing: its creator's, or the tenant's automation principal's as the
        transition answers for its grant. None when the creator holds no
        place in the tenant now, no principal is granted, or the grant is
        above the creator's role now: the session's calls are answered by
        the grant alone, so a firing that would lend its creator a role
        starts nothing."""
        try:
            creator = await self._live(
                ctx, ctx.org_id, Principal(kind=PrincipalKind.PERSON, id=automation.created_by)
            )
        except NotAuthorized:
            return None
        if automation.runs_as is not RunsAs.AUTOMATION_PRINCIPAL:
            return creator
        granted = await self._storage.read_principal(ctx.org_id)
        if granted is None:
            return None
        try:
            live = await self._live(
                ctx, ctx.org_id, Principal(kind=PrincipalKind.SERVICE, id=granted.id)
            )
        except NotAuthorized:
            return None
        if not role_at_most(live.role, creator.role):
            return None
        return live

    async def _audit(self, ctx: TenantContext, granted: AutomationPrincipal) -> None:
        facts = {"role": granted.role.value}
        await self._events.append_event(ctx, audit_event(ctx, new_id(), GRANTED, granted.id, facts))

    async def _enabled(self, ctx: TenantContext) -> list[Automation]:
        found: list[Automation] = []
        after: UUID | None = None
        while True:
            page = await self._storage.read_automations(ctx.org_id, after, self._options.page)
            found.extend(a for a in page if a.enabled)
            if len(page) < self._options.page:
                return found
            after = page[-1].id
