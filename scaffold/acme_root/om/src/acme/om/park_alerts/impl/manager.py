import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.infra.exceptions import InfraException
from acme.integrations.events import IntegrationInterface
from acme.om.agent_billing.rules import ANOMALY_UNLOCK, FUNDS_UNLOCK
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.rules import QUESTION
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agent_steps.types.header import Park, ParkReason, ToolRequestHeader
from acme.om.agents.loop_rules import APPROVAL_UNLOCK
from acme.om.agents.types.run import LoopRun, RunEnd
from acme.om.base import OmBase, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.evidence.types.provenance import Provenance
from acme.om.exceptions import NotFound
from acme.om.intake import IntakeManagerInterface
from acme.om.park_alerts.manager import ParkAlertsManagerInterface
from acme.om.park_alerts.rules import (
    ANSWER_QUESTION,
    APPROVES_CALLS,
    FIXES_AT_PROVIDER,
    NO_ROUTE,
    SAVES_KEYS,
    SETS_SPEND_BUDGETS,
    UNNAMED,
    answer_link,
    approval_link,
    as_budget,
    asked_question,
    budget_link,
    decision_link,
    first_try,
    fixed_at_provider,
    held_calls,
    holding,
    holding_permission,
    key_link,
    message_link,
    missing_key,
    named,
    needs_person,
    park_alert_id,
    parked_step,
    question_text,
    requester_or_managers,
)
from acme.om.park_alerts.storage import ParkAlertStorageInterface
from acme.om.park_alerts.types.park_alert import PORTAL, Ask, ParkAlert
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tenancy.types.membership import Membership
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.tools.rules import approver_roles

log = logging.getLogger(__name__)


class ParkAlertsOptions(OmBase):
    page: int = Field(default=200, gt=0)
    max_page: int = Field(default=200, gt=0)
    purge_batch: int = Field(default=1000, gt=0)


def asked(
    action: str,
    link: str,
    say: Callable[[str], str],
    title: str,
    recipients: tuple[UUID, ...],
) -> Ask:
    """An ask that `say`s what waits: its row of the session `UNNAMED`, and a
    post of the session by its `title`, opened, so the row quotes nothing
    sealed."""
    return Ask(
        action=action, link=link, text=say(UNNAMED), posted=say(title), recipients=recipients
    )


class ParkAlertsManagerImpl(ParkAlertsManagerInterface):
    def __init__(
        self,
        storage: ParkAlertStorageInterface,
        sessions: AgentSessionsManagerInterface,
        steps: AgentStepsManagerInterface,
        tools: ToolsManagerInterface,
        tenancy: TenancyManagerInterface,
        intake: IntakeManagerInterface,
        integrations: Callable[[str], IntegrationInterface],
        options: ParkAlertsOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._sessions = sessions
        self._steps = steps
        self._tools = tools
        self._tenancy = tenancy
        self._intake = intake
        self._integrations = integrations
        self._options = options
        self._clock = clock

    async def notify_park(self, ctx: TenantContext, run: LoopRun) -> tuple[ParkAlert, ...]:
        ctx.require(Permission.WRITE)
        park = run.park
        if run.end is not RunEnd.PARKED or park is None or not needs_person(park):
            return ()
        session = await self._sessions.get_agent_session(ctx, run.agent_session_id)
        history = await self._history(ctx, session.id)
        parked = parked_step(history, park)
        if parked is None:
            # The session moved on from the park this run wrote.
            return ()
        if park.retry_at is not None:
            # It tries again by itself, and each try writes it again: it is
            # told once, at its first try.
            parked = first_try(history, parked)
        members = await self._members(ctx)
        told: list[ParkAlert] = []
        for ask in await self._asks(ctx, session, park, history, members):
            for recipient in ask.recipients:
                told.extend(await self._tell(ctx, session, park, parked, ask, recipient))
        return tuple(told)

    async def get_park_alerts(self, ctx: TenantContext, limit: int) -> tuple[ParkAlert, ...]:
        ctx.require(Permission.READ)
        bounded = max(1, min(limit, self._options.max_page))
        return tuple(await self._storage.read_park_alerts(ctx.org_id, ctx.user_id, bounded))

    async def mark_read(self, ctx: TenantContext, park_alert_id: UUID) -> ParkAlert:
        # A person's own list: marking it read changes nothing of the
        # tenant's, so reading is all it asks.
        ctx.require(Permission.READ)
        marked = await self._storage.mark_read(
            ctx.org_id, ctx.user_id, park_alert_id, self._clock()
        )
        if marked is None:
            raise NotFound(f"park alert {park_alert_id} not found")
        return marked

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    # What a park asks, and of whom.

    async def _asks(
        self,
        ctx: TenantContext,
        session: AgentSession,
        park: Park,
        history: Sequence[AgentStep],
        members: Sequence[Membership],
    ) -> list[Ask]:
        # The title is content: the row names the session `UNNAMED`, and a
        # post names it by its title, opened here.
        (opened,) = await self._sessions.open_titles(ctx, [session])
        title = named(opened.title.said())
        if park.reason is ParkReason.PERSON and park.unlock == APPROVAL_UNLOCK:
            policy = await self._tools.get_policy(ctx)
            asks: list[Ask] = []
            for request in held_calls(history):
                header = request.header
                assert isinstance(header, ToolRequestHeader)
                roles = approver_roles(policy, header.authorization_class)
                asks.append(
                    asked(
                        "decide_call",
                        decision_link(session.id, request),
                        lambda name, tool=header.tool: (
                            f"{name}: a call to {tool} waits for your decision."
                        ),
                        title,
                        holding(members, roles),
                    )
                )
            return asks
        budget = as_budget(park.unlock) if park.reason is ParkReason.SPEND_BUDGET else None
        if budget is not None:
            return [
                asked(
                    "raise_budget",
                    budget_link(budget),
                    lambda name: f"{name} waits for a raise of budget {budget}.",
                    title,
                    holding_permission(members, SETS_SPEND_BUDGETS),
                )
            ]
        if park.reason is ParkReason.SPEND_BUDGET and park.unlock == FUNDS_UNLOCK:
            return [
                asked(
                    "top_up",
                    NO_ROUTE,
                    lambda name: f"{name} waits for funds: the account is spent.",
                    title,
                    holding_permission(members, SETS_SPEND_BUDGETS),
                )
            ]
        if park.reason is ParkReason.PERSON and park.unlock == ANOMALY_UNLOCK:
            # The requester cannot clear it: approving a call past its
            # session's norm is agent billing's, and takes its permission.
            return [
                asked(
                    "approve_call",
                    approval_link(session.id),
                    lambda name: (
                        f"{name}: a call costs far more than the session's others,"
                        " and waits for your approval."
                    ),
                    title,
                    holding_permission(members, APPROVES_CALLS),
                )
            ]
        provider = fixed_at_provider(park)
        if provider is not None:
            # Fixed at the provider, and nothing tells the platform: the
            # session tries again by itself, and takes the fix at its next try.
            cause = park.cause
            return [
                asked(
                    "fix_at_provider",
                    NO_ROUTE,
                    lambda name: f"{name} waits: {cause}. It tries again by itself.",
                    title,
                    holding_permission(members, FIXES_AT_PROVIDER),
                )
            ]
        provider = missing_key(park)
        if provider is not None:
            # The requester cannot clear it: the org's keys are saved by
            # those who manage it, and its other sessions wait on the same key.
            why = park.cause or f"the org holds no {provider} key"
            return [
                asked(
                    "save_key",
                    key_link(provider),
                    lambda name: f"{name} waits: {why}.",
                    title,
                    holding_permission(members, SAVES_KEYS),
                )
            ]
        # A question, and any other park on a person, waits on the person who
        # asked; one who holds no place now leaves it to the people who
        # manage the tenant.
        requester = session.speaker.id if session.speaker is not None else session.created_by
        recipients = requester_or_managers(requester, members)
        if park == QUESTION:
            # Only a principal's message answers it: a control re-parks it.
            return [
                Ask(
                    action=ANSWER_QUESTION,
                    link=message_link(session.id),
                    text=question_text(UNNAMED, None),
                    posted=question_text(title, asked_question(history)),
                    recipients=recipients,
                )
            ]
        unlock = park.unlock
        return [
            asked(
                unlock,
                answer_link(session.id),
                lambda name: f"{name} waits for you: {unlock}.",
                title,
                recipients,
            )
        ]

    async def _tell(
        self,
        ctx: TenantContext,
        session: AgentSession,
        park: Park,
        parked: AgentStep,
        ask: Ask,
        recipient: UUID,
    ) -> list[ParkAlert]:
        """One recipient on each of their channels: the platform's own list,
        and each account of theirs an integration holds. A post an
        integration cannot make now is left out, and the list still tells
        them."""
        channels = [(PORTAL, "")]
        for link in await self._intake.get_links(ctx, recipient):
            channels.append((link.integration, link.external_id))
        told: list[ParkAlert] = []
        for channel, address in channels:
            park_alert_id_ = park_alert_id(parked, ask.action, ask.link, recipient, channel)
            held = await self._storage.read_park_alert(ctx.org_id, park_alert_id_)
            if held is not None:
                told.append(held)
                continue
            provenance: Provenance | None = None
            if channel != PORTAL:
                said = ask.posted or ask.text
                try:
                    posted = await self._integrations(channel).post(
                        address, f"{said} {ask.link}" if ask.link else said
                    )
                except InfraException:
                    log.warning(
                        "%s could not tell %s of session %s", channel, recipient, session.id
                    )
                    continue
                provenance = Provenance(posted.provenance)
            park_alert = ParkAlert(
                id=park_alert_id_,
                created_at=self._clock(),
                recipient=recipient,
                agent_session_id=session.id,
                park_step=parked.id,
                reason=park.reason,
                unlock=park.unlock,
                action=ask.action,
                link=ask.link,
                channel=channel,
                address=address,
                provenance=provenance,
                text=ask.text,
            )
            await self._storage.create_park_alert(ctx.org_id, park_alert)
            told.append(park_alert)
        return told

    async def _history(self, ctx: TenantContext, agent_session_id: UUID) -> list[AgentStep]:
        steps: list[AgentStep] = []
        while True:
            after = steps[-1].seq if steps else 0
            page = await self._steps.get_agent_steps(
                ctx, agent_session_id, after, self._options.page
            )
            steps.extend(page.items)
            if not page.has_more or not page.items:
                return steps

    async def _members(self, ctx: TenantContext) -> list[Membership]:
        members: list[Membership] = []
        after: UUID | None = None
        while True:
            page = await self._tenancy.members.get_memberships(ctx, after, self._options.page)
            members.extend(page.items)
            if not page.has_more or not page.items:
                return members
            after = page.items[-1].user_id
