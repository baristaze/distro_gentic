import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field
from pydantic import ValidationError as ShapeError

from acme.om.agent_automations.actions import AgentAutomationActionInterface, AgentAutomationActions
from acme.om.agent_automations.manager import AgentAutomationsManagerInterface
from acme.om.agent_automations.rules import hop_after, ignored, matches, slot
from acme.om.agent_automations.storage import AgentAutomationStorageInterface
from acme.om.agent_automations.types.agent_automation import (
    PLATFORM_ACTIONS,
    ActionKind,
    AgentAutomation,
    AgentAutomationPrincipal,
    AgentAutomationRun,
    Firing,
    Refusal,
    RunOutcome,
    RunsAs,
    RunStatus,
)
from acme.om.agent_playbooks import AgentPlaybooksManagerInterface
from acme.om.agent_playbooks.types.agent_playbook import AgentPlaybook
from acme.om.agent_projects import AgentProjectsManagerInterface
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import AgentSessionStatus
from acme.om.agent_steps.rules import message_step
from acme.om.agent_steps.types.agent_step import Actor, AgentStep, AgentStepType, Origin
from acme.om.agent_steps.types.content import Content, TextBlock
from acme.om.agent_steps.types.header import InputHeader
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.request import Start
from acme.om.attribution import PrincipalContext
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import OmBase, derived_id, new_id, utcnow
from acme.om.change_events import ChangeEventsManagerInterface
from acme.om.change_events.manager import audit_change_event
from acme.om.context import Permission, Role, TenantContext
from acme.om.exceptions import NotAuthorized, NotFound, OmException, ValidationFailed
from acme.om.intake.rules import in_person
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import outbox_row, versioned_row
from acme.om.spend_budgets import SpendBudgetsManagerInterface
from acme.om.spend_budgets.types.spend_budget import SpendBudget, SpendBudgetScopeKind, WindowKind
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tenancy.rules import role_at_most

log = logging.getLogger(__name__)

CREATED = "agent_automations.agent_automation.created"
UPDATED = "agent_automations.agent_automation.updated"
GRANTED = "agent_automations.principal.granted"
UNHELD = (
    "a message to a standing session is refused: no budget on a session ends "
    "with a run, so nothing would hold the run to its run_cap_micros"
)
"""Why a `message_session` action never acts (ADR 2036)."""
EVENT_RUN_SEED = "automation"
"""The part an event's run id is derived with, before the automation's id.
Its bytes are fixed, whatever the noun is called, so the id stays the one
every release derived: an event delivered again finds the run it made."""


class AgentAutomationsOptions(OmBase):
    # The most agent automations one firing reads a page, and runs one read takes.
    page: int = Field(default=200, gt=0)
    # A started run that names no session, and no work of a product's
    # action, this long after it started was lost before its action ran: it
    # is closed, and its reservation goes with its period.
    lost_after: timedelta = timedelta(minutes=5)
    max_page: int = Field(default=200, gt=0)
    purge_batch: int = Field(default=1000, gt=0)


class AgentAutomationsManagerImpl(AgentAutomationsManagerInterface):
    def __init__(
        self,
        storage: AgentAutomationStorageInterface,
        agents: AgentsManagerInterface,
        sessions: AgentSessionsManagerInterface,
        budgets: SpendBudgetsManagerInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        events: ChangeEventsManagerInterface,
        agent_projects: AgentProjectsManagerInterface,
        principal_context: PrincipalContext,
        options: AgentAutomationsOptions,
        clock: Callable[[], datetime] = utcnow,
        *,
        agent_project_required: bool,
        actions: AgentAutomationActions | None = None,
        agent_playbooks: Callable[[], AgentPlaybooksManagerInterface] | None = None,
    ) -> None:
        """`agent_project_required` refuses a start that names no agent project: what
        every stack but a local one sets, so no per-agent-project policy is
        skipped by a session an agent automation starts. `actions` are the
        product's own kinds of action; None declares none. `agent_playbooks`
        answers the agent playbooks a start invokes; None keeps none, so a start
        that names one is refused when it is saved and when it fires."""
        self._storage = storage
        self._agents = agents
        self._agent_projects = agent_projects
        self._project_required = agent_project_required
        self._sessions = sessions
        self._budgets = budgets
        self._tenancy = tenancy
        self._relay = relay
        self._change_events = events
        self._live = principal_context
        self._options = options
        self._clock = clock
        self._actions = actions or AgentAutomationActions(())
        self._agent_playbooks = agent_playbooks

    async def create_agent_automation(
        self, ctx: TenantContext, agent_automation: AgentAutomation
    ) -> AgentAutomation:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("an agent automation is made by a person, never by an agent's call")
        await self._check_principal(ctx, agent_automation)
        await self._check_kind(ctx, agent_automation)
        await self._check_agent_project(ctx, agent_automation)
        await self._check_agent_playbook(ctx, agent_automation)
        now = self._clock()
        made = AgentAutomation.model_validate(
            {
                **agent_automation.model_dump(),
                "created_at": now,
                "updated_at": now,
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
            }
        )
        rows = (versioned_row(ctx, CREATED, made.id, 1),)
        if await self._storage.create_agent_automation(ctx.org_id, made, rows):
            await self._relay.relay_all(ctx.org_id, rows)
        return await self.get_agent_automation(ctx, made.id)

    async def update_agent_automation(
        self, ctx: TenantContext, agent_automation_id: UUID, agent_automation: AgentAutomation
    ) -> AgentAutomation:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized(
                "an agent automation is edited by a person, never by an agent's call"
            )
        stored = await self.get_agent_automation(ctx, agent_automation_id)
        if agent_automation.runs_as is RunsAs.CREATOR and stored.created_by != ctx.user_id:
            raise NotAuthorized(
                "an agent automation that runs as its creator is edited by its creator alone"
            )
        await self._check_principal(ctx, agent_automation)
        await self._check_kind(ctx, agent_automation)
        await self._check_agent_project(ctx, agent_automation)
        await self._check_agent_playbook(ctx, agent_automation)
        # The editor is its creator from here on: one that runs as its
        # creator is its creator's to edit, and one that runs as the
        # principal fires on its creator's role, which is the editor's that
        # `_check_principal` held to the grant.
        edited = AgentAutomation.model_validate(
            {
                **agent_automation.model_dump(),
                "id": stored.id,
                "created_at": stored.created_at,
                "created_by": ctx.user_id,
                "updated_at": self._clock(),
                "updated_by": ctx.user_id,
            }
        )
        rows = (outbox_row(ctx, UPDATED, edited.id, {}),)
        if not await self._storage.write_agent_automation(ctx.org_id, edited, rows):
            raise NotFound(f"agent automation {agent_automation_id} not found")
        await self._relay.relay_all(ctx.org_id, rows)
        return edited

    async def list_agent_automations(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> tuple[AgentAutomation, ...]:
        ctx.require(Permission.READ)
        limit = max(1, min(limit, self._options.max_page))
        return tuple(await self._storage.read_agent_automations(ctx.org_id, after, limit))

    async def grant_principal(self, ctx: TenantContext, role: Role) -> AgentAutomationPrincipal:
        ctx.require(Permission.MANAGE_MEMBERS)
        if not in_person(ctx):
            raise NotAuthorized("an agent automation principal is granted by a person, in person")
        if not role_at_most(role, ctx.role):
            raise NotAuthorized(f"a {ctx.role.value} grants no {role.value} principal")
        granted = await self._storage.write_principal(
            ctx.org_id,
            AgentAutomationPrincipal(
                id=new_id(), created_at=self._clock(), role=role, granted_by=ctx.user_id
            ),
        )
        await self._audit(ctx, granted)
        return granted

    async def get_principal(self, ctx: TenantContext) -> AgentAutomationPrincipal:
        ctx.require(Permission.READ)
        found = await self._storage.read_principal(ctx.org_id)
        if found is None:
            raise NotFound("no agent automation principal is granted")
        return found

    async def get_agent_automation(
        self, ctx: TenantContext, agent_automation_id: UUID
    ) -> AgentAutomation:
        ctx.require(Permission.READ)
        found = await self._storage.read_agent_automation(ctx.org_id, agent_automation_id)
        if found is None:
            raise NotFound(f"agent automation {agent_automation_id} not found")
        return found

    async def get_runs(
        self, ctx: TenantContext, agent_automation_id: UUID, limit: int
    ) -> tuple[AgentAutomationRun, ...]:
        ctx.require(Permission.READ)
        bounded = max(1, min(limit, self._options.max_page))
        return tuple(await self._storage.read_runs(ctx.org_id, agent_automation_id, bounded))

    async def fire(self, ctx: TenantContext, firing: Firing) -> tuple[AgentAutomationRun, ...]:
        ctx.require(Permission.WRITE)
        cause = None
        if firing.caused_by is not None:
            cause = await self._storage.read_session_run(ctx.org_id, firing.caused_by)
        runs: list[AgentAutomationRun] = []
        for agent_automation in await self._enabled(ctx):
            if not matches(agent_automation.trigger, firing):
                continue
            runs.extend(await self._drain(ctx, agent_automation))
            runs.append(await self._fire_one(ctx, agent_automation, firing, cause))
        return tuple(runs)

    async def tick(self, ctx: TenantContext) -> tuple[AgentAutomationRun, ...]:
        ctx.require(Permission.WRITE)
        now = self._clock()
        runs: list[AgentAutomationRun] = []
        for agent_automation in await self._enabled(ctx):
            try:
                runs.extend(await self._tick_one(ctx, agent_automation, now))
            except Exception:
                # One agent automation that fails never stops the tenant's others:
                # its queue and its slot are asked again at the next tick.
                log.exception(
                    "agent automation %s of org %s failed its tick", agent_automation.id, ctx.org_id
                )
        return tuple(runs)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    # A firing.

    async def _tick_one(
        self, ctx: TenantContext, agent_automation: AgentAutomation, now: datetime
    ) -> list[AgentAutomationRun]:
        """Its queued runs as its limits start them, and its schedule's slot
        at `now` when no run holds it yet."""
        runs = await self._drain(ctx, agent_automation)
        at = slot(agent_automation.trigger, agent_automation.created_at, now)
        if at is None:
            return runs
        run_id = derived_id(agent_automation.id, at, "schedule")
        if await self._storage.read_run(ctx.org_id, run_id) is not None:
            return runs
        runs.append(await self._fire_one(ctx, agent_automation, Firing(), None, run_id=run_id))
        return runs

    async def _fire_one(
        self,
        ctx: TenantContext,
        agent_automation: AgentAutomation,
        firing: Firing,
        cause: AgentAutomationRun | None,
        *,
        run_id: UUID | None = None,
    ) -> AgentAutomationRun:
        now = self._clock()
        # One run an event, and one a schedule's slot: a redelivered event,
        # or another worker's tick in the slot, finds the run it made.
        run_id = run_id or new_id()
        if firing.event_id is not None and firing.occurred_at is not None:
            run_id = derived_id(
                firing.event_id, firing.occurred_at, f"{EVENT_RUN_SEED}:{agent_automation.id}"
            )
        run = AgentAutomationRun(
            id=run_id,
            created_at=now,
            agent_automation_id=agent_automation.id,
            event_id=firing.event_id,
            caused_by=firing.caused_by,
            status=RunStatus.REFUSED,
            refusal=Refusal.HOP_LIMIT,
            hop=hop_after(cause),
            event_text=firing.text,
        )
        stop = ignored(agent_automation, firing, cause)
        if stop is not None:
            return await self._storage.create_run(
                ctx.org_id, run.model_copy(update={"refusal": stop, "event_text": ""})
            )
        return await self._admit(ctx, agent_automation, run)

    async def _admit(
        self, ctx: TenantContext, agent_automation: AgentAutomation, run: AgentAutomationRun
    ) -> AgentAutomationRun:
        """Asks the limits, and runs the action of a run they start. A start
        that names no agent project where one is required, and an agent automation whose
        principal cannot act, are refused before the limits hold anything."""
        if self._outside_agent_projects(agent_automation):
            # Saved before an agent project was required, or under a local stack:
            # its session would take no agent project's budget or policy.
            return await self._refuse(ctx, run, Refusal.AGENT_PROJECT)
        if self._unknown_kind(agent_automation):
            # Its product's kind left this process's registry since it was
            # saved: nothing would act on it.
            return await self._refuse(ctx, run, Refusal.ACTION)
        if agent_automation.action.kind == ActionKind.MESSAGE_SESSION:
            # One stored enabled never acts: its woken session's spend would
            # be held to no cap.
            log.info("run %s of org %s is refused: %s", run.id, ctx.org_id, UNHELD)
            return await self._refuse(ctx, run, Refusal.ACTION)
        creator = await self._runs_as(ctx, agent_automation)
        if creator is None:
            return await self._refuse(ctx, run, Refusal.PRINCIPAL)
        await self._close_finished(ctx, agent_automation)
        landed = await self._storage.admit(ctx.org_id, run, agent_automation.limits, self._clock())
        acted = landed.agent_session_id is not None or landed.work_id is not None
        if landed.status is not RunStatus.STARTED or acted:
            return landed
        try:
            return await self._act(ctx, creator, agent_automation, landed)
        except OmException:
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
        agent_automation: AgentAutomation,
        run: AgentAutomationRun,
    ) -> AgentAutomationRun:
        """The action of a started run, as its creator. A started session is
        held to the run's reservation by a budget on its tree before anything
        wakes it; the agent playbook it invokes arrives first, the event reaches
        it as data, and the brief as the creator's message. A product's
        action is its kind's to run. A message to a standing session is
        refused before it gets here."""
        action = agent_automation.action
        kind = self._actions.get(action.kind)
        if kind is not None:
            return await self._act_product(ctx, creator, kind, agent_automation, run)
        assert action.kind == ActionKind.START_SESSION  # `_admit` refuses a message
        assert action.brief is not None and action.agent_kind is not None
        assert action.title is not None
        # The agent playbook's version is read before anything is made: a name
        # with none refuses the run, and no session is started.
        agent_playbook = (
            None
            if action.agent_playbook is None
            else await self._agent_playbook(creator, action.agent_playbook)
        )
        start = Start(
            id=derived_id(run.id, run.created_at, "session"),
            kind=action.agent_kind,
            title=action.title,
        )
        # In its agent project from its first moment, so the agent project's budget
        # and policies hold every call it makes.
        session = (
            await self._agents.start_agent_session(creator, start)
            if action.agent_project_id is None
            else await self._agent_projects.start_agent_session(
                creator, action.agent_project_id, start
            )
        )
        budget = SpendBudget(
            id=derived_id(run.id, run.created_at, "budget"),
            created_at=run.created_at,
            updated_at=run.created_at,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            scope_kind=SpendBudgetScopeKind.TREE,
            scope_key=str(session.root_id),
            window_kind=WindowKind.LIFE,
            cost_micros=run.reserved_micros,
        )
        await self._budgets.create_spend_budget(ctx, budget)
        agent_session_id, spend_budget_id = session.id, budget.id
        if agent_playbook is not None and self._agent_playbooks is not None:
            # Its gates hold before anything else arrives, and its brief is
            # the creator's message, as an invocation in person is.
            await self._agent_playbooks().invoke_version(
                creator, agent_session_id, agent_playbook.id
            )
        inputs: list[AgentStep] = []
        if run.event_text:
            inputs.append(self._event_step(ctx, run, agent_session_id))
        brief = message_step(
            derived_id(run.id, run.created_at, "brief"),
            self._clock(),
            agent_session_id,
            creator,
            action.brief,
        )
        inputs.append(brief)
        await self._sessions.receive(creator, agent_session_id, inputs)
        # The session's history holds the event from here on, under its key;
        # the run keeps none of it. A run lost before this write is acted on
        # again, under the same ids, and lands nothing twice.
        acted = run.model_copy(
            update={
                "agent_session_id": agent_session_id,
                "opened": True,
                "spend_budget_id": spend_budget_id,
                "event_text": "",
            }
        )
        await self._storage.write_run(ctx.org_id, acted)
        return acted

    async def _act_product(
        self,
        ctx: TenantContext,
        creator: TenantContext,
        kind: AgentAutomationActionInterface,
        agent_automation: AgentAutomation,
        run: AgentAutomationRun,
    ) -> AgentAutomationRun:
        """A product's action, run by its kind as the agent automation runs; the
        run keeps the id of the work it started, and is at work until the
        kind's check says that work ended."""
        try:
            params = kind.params.model_validate(agent_automation.action.plain_params())
        except ShapeError as exc:
            # Saved under an earlier shape of its kind: refused, never acted on.
            raise ValidationFailed(f"the params of {kind.name} are malformed: {exc}") from exc
        work_id = await kind.act(creator, run, params)
        acted = run.model_copy(update={"work_id": work_id, "event_text": ""})
        await self._storage.write_run(ctx.org_id, acted)
        return acted

    def _event_step(
        self, ctx: TenantContext, run: AgentAutomationRun, agent_session_id: UUID
    ) -> AgentStep:
        """The event that fired a run, as data: it never waits to wake the
        session, since the brief that follows it does."""
        agent_step_id = derived_id(run.id, run.created_at, "event")
        return AgentStep(
            id=agent_step_id,
            created_at=self._clock(),
            agent_session_id=agent_session_id,
            loop_id=agent_step_id,
            type=AgentStepType.EVENT,
            actor=Actor.EXTERNAL,
            origin=Origin.AUTOMATION,
            header=InputHeader(
                waking=False, principal=Principal(kind=PrincipalKind.SERVICE, id=ctx.user_id)
            ),
            content=Content(blocks=(TextBlock(text=run.event_text),)),
        )

    async def _drain(
        self, ctx: TenantContext, agent_automation: AgentAutomation
    ) -> list[AgentAutomationRun]:
        """Its queued runs, oldest first, while its limits start them."""
        moved: list[AgentAutomationRun] = []
        queued = await self._storage.read_queued_runs(
            ctx.org_id, agent_automation.id, self._options.page
        )
        for run in queued:
            landed = await self._admit(ctx, agent_automation, run)
            if landed.status is RunStatus.QUEUED:
                break
            moved.append(landed)
        return moved

    async def _close_finished(self, ctx: TenantContext, agent_automation: AgentAutomation) -> None:
        """Closes the runs whose session's tree is no longer at work, and
        those whose product's work ended as its kind's check says, with the
        outcome it said, so the concurrency counts the ones that are."""
        now = self._clock()
        for run in await self._storage.read_open_runs(
            ctx.org_id, agent_automation.id, self._options.page
        ):
            outcome: RunOutcome | None = None
            if run.work_id is not None:
                outcome = await self._ended(ctx, agent_automation, run)
                done = outcome is not None
            elif run.agent_session_id is None:
                # From its start, never from when it was queued: a run that
                # waited in the queue is still starting its action.
                started = run.started_at or run.created_at
                done = now - started >= self._options.lost_after
            else:
                done = await self._tree_idle(ctx, run.agent_session_id)
            if done:
                closed = run.model_copy(
                    update={"closed_at": now, "event_text": "", "outcome": outcome}
                )
                await self._storage.write_run(ctx.org_id, closed)

    async def _tree_idle(self, ctx: TenantContext, root_id: UUID) -> bool:
        """Whether no session of the tree a run started is pending,
        running, or parked: a root that waits idle on a sub-agent still
        holds its run's place. The tree is read twice, and is idle only when
        both reads find every session idle at one version, since a report
        or a spawn that lands while it is read moves one. A root that is
        gone holds nothing."""
        try:
            first = await self._idle_versions(ctx, root_id)
            return first is not None and first == await self._idle_versions(ctx, root_id)
        except NotFound:
            return True

    async def _idle_versions(
        self, ctx: TenantContext, root_id: UUID
    ) -> list[tuple[UUID, int]] | None:
        """Each session of the tree with its version, from the root down,
        when every one is idle; None at the first one that is not. The
        tree's own bounds keep the walk short."""
        root = await self._sessions.get_agent_session(ctx, root_id)
        if root.status is not AgentSessionStatus.IDLE:
            return None
        seen = [(root.id, root.version)]
        parents = [root.id]
        while parents:
            parent_id, after = parents.pop(), None
            while True:
                page = await self._sessions.get_children(ctx, parent_id, after, self._options.page)
                for child in page.items:
                    if child.status is not AgentSessionStatus.IDLE:
                        return None
                    seen.append((child.id, child.version))
                    parents.append(child.id)
                if not page.has_more or not page.items:
                    break
                after = page.items[-1].id
        return seen

    async def _ended(
        self, ctx: TenantContext, agent_automation: AgentAutomation, run: AgentAutomationRun
    ) -> RunOutcome | None:
        """How a product's work ended, as its kind's check says. A check
        that fails, or a kind this process no longer knows, leaves the run
        open: its work may still be at work, so it is never closed as
        lost, and the next firing asks again."""
        kind = self._actions.get(agent_automation.action.kind)
        if kind is None:
            return None
        try:
            return await kind.ended(ctx, run)
        except Exception:
            log.exception("the check of run %s of org %s failed", run.id, ctx.org_id)
            return None

    async def _refuse(
        self, ctx: TenantContext, run: AgentAutomationRun, refusal: Refusal
    ) -> AgentAutomationRun:
        """The run refused before the limits were asked: it starts nothing
        and reserves nothing. A queued run is rewritten, and a new one made."""
        refused = run.model_copy(
            update={"status": RunStatus.REFUSED, "refusal": refusal, "event_text": ""}
        )
        if run.status is RunStatus.QUEUED:
            await self._storage.write_run(ctx.org_id, refused)
            return refused
        return await self._storage.create_run(ctx.org_id, refused)

    async def _check_principal(self, ctx: TenantContext, agent_automation: AgentAutomation) -> None:
        """One that runs as the agent automation principal is made or edited only
        once a principal is granted, by a caller whose role is at least the
        grant."""
        if agent_automation.runs_as is not RunsAs.AGENT_AUTOMATION_PRINCIPAL:
            return
        granted = await self._storage.read_principal(ctx.org_id)
        if granted is None:
            raise NotAuthorized("an agent automation runs as no principal before one is granted")
        if not role_at_most(granted.role, ctx.role):
            raise NotAuthorized(
                f"a {ctx.role.value} makes no agent automation that runs as a {granted.role.value}"
            )

    async def _check_kind(self, ctx: TenantContext, agent_automation: AgentAutomation) -> None:
        """A product's action names a kind a product declares, and its params
        hold to that kind's shape: otherwise it is `ValidationFailed`, so no
        agent automation is written that could never act. An enabled one is then
        its kind's to check against its writer and whom it runs as, whose
        refusal answers as is, so a writer its firings would refuse is told
        now. A disabled one is
        not asked: nothing deletes an agent automation, so turning it off always
        goes through, and turning it on again is an edit the kind checks.
        An enabled message to a standing session is `ValidationFailed`
        (`UNHELD`): nothing would hold its run to its cap."""
        action = agent_automation.action
        if action.kind == ActionKind.MESSAGE_SESSION and agent_automation.enabled:
            raise ValidationFailed(UNHELD)
        if action.kind in PLATFORM_ACTIONS:
            return
        kind = self._actions.get(action.kind)
        if kind is None:
            raise ValidationFailed(f"no product declares the action kind {action.kind}")
        try:
            params = kind.params.model_validate(action.plain_params())
        except ShapeError as exc:
            raise ValidationFailed(f"the params of {action.kind} are malformed: {exc}") from exc
        if agent_automation.enabled:
            await kind.check_writer(ctx, params, agent_automation.runs_as)

    def _unknown_kind(self, agent_automation: AgentAutomation) -> bool:
        kind = agent_automation.action.kind
        return kind not in PLATFORM_ACTIONS and self._actions.get(kind) is None

    async def _check_agent_playbook(
        self, ctx: TenantContext, agent_automation: AgentAutomation
    ) -> None:
        """A start that invokes an agent playbook names one the tenant published:
        otherwise it is `ValidationFailed`, so no agent automation is written
        whose firings would all be refused."""
        name = agent_automation.action.agent_playbook
        if name is None:
            return
        try:
            await self._agent_playbook(ctx, name)
        except NotFound as missing:
            raise ValidationFailed(f"no agent playbook {name} is published to invoke") from missing

    async def _agent_playbook(self, ctx: TenantContext, name: str) -> AgentPlaybook:
        """The name's latest version; none, or no agent playbooks in this
        process, is `NotFound`."""
        if self._agent_playbooks is None:
            raise NotFound(f"no agent playbook {name} is kept in this process")
        return await self._agent_playbooks().get_agent_playbook(ctx, name)

    async def _check_agent_project(
        self, ctx: TenantContext, agent_automation: AgentAutomation
    ) -> None:
        """A start's agent project is one of the caller's tenant: another tenant's
        is `NotFound`, as one that never existed is. One that names none is
        `ValidationFailed` where a session starts in an agent project."""
        agent_project_id = agent_automation.action.agent_project_id
        if agent_project_id is not None:
            await self._agent_projects.get_agent_project(ctx, agent_project_id)
        elif self._outside_agent_projects(agent_automation):
            raise ValidationFailed(
                "an agent automation's session starts in an agent project: name its agent_project_id"
            )

    def _outside_agent_projects(self, agent_automation: AgentAutomation) -> bool:
        """A start that names no agent project where a session starts in one."""
        action = agent_automation.action
        return (
            self._project_required
            and action.kind == ActionKind.START_SESSION
            and action.agent_project_id is None
        )

    async def _runs_as(
        self, ctx: TenantContext, agent_automation: AgentAutomation
    ) -> TenantContext | None:
        """The live context the agent automation's action runs under, read at the
        firing: its creator's, or the tenant's agent automation principal's as the
        transition answers for its grant. None when the creator holds no
        place in the tenant now, no principal is granted, or the grant is
        above the creator's role now: the session's calls are answered by
        the grant alone, so a firing that would lend its creator a role
        starts nothing."""
        try:
            creator = await self._live(
                ctx,
                ctx.org_id,
                Principal(kind=PrincipalKind.PERSON, id=agent_automation.created_by),
            )
        except NotAuthorized:
            return None
        if agent_automation.runs_as is not RunsAs.AGENT_AUTOMATION_PRINCIPAL:
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

    async def _audit(self, ctx: TenantContext, granted: AgentAutomationPrincipal) -> None:
        facts = {"role": granted.role.value}
        await self._change_events.append_change_event(
            ctx, audit_change_event(ctx, new_id(), GRANTED, granted.id, facts)
        )

    async def _enabled(self, ctx: TenantContext) -> list[AgentAutomation]:
        found: list[AgentAutomation] = []
        after: UUID | None = None
        while True:
            page = await self._storage.read_agent_automations(ctx.org_id, after, self._options.page)
            found.extend(a for a in page if a.enabled)
            if len(page) < self._options.page:
                return found
            after = page[-1].id
