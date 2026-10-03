import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.infra.exceptions import InfraException
from acme.integrations.events import IntegrationInterface
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents.loop_rules import APPROVAL_UNLOCK
from acme.om.agents.types.run import LoopRun, RunEnd
from acme.om.base import Platform, utcnow
from acme.om.billing.rules import ANOMALY_UNLOCK, FUNDS_UNLOCK
from acme.om.context import Permission, TenantContext
from acme.om.evidence.types.provenance import Provenance
from acme.om.intake import IntakeManagerInterface
from acme.om.notifications.manager import NotificationsManagerInterface
from acme.om.notifications.rules import (
    APPROVES_CALLS,
    NO_ROUTE,
    SETS_BUDGETS,
    answer_link,
    as_budget,
    decision_link,
    held_calls,
    holding,
    holding_permission,
    needs_person,
    notification_id,
    parked_step,
)
from acme.om.notifications.storage import NotificationStorageInterface
from acme.om.notifications.types.notification import PORTAL, Ask, Notification
from acme.om.steps import StepsManagerInterface
from acme.om.steps.types.header import Park, ParkReason, ToolRequestHeader
from acme.om.steps.types.step import Step
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tenancy.types.membership import Membership
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.tools.rules import approver_roles

log = logging.getLogger(__name__)


class NotificationsOptions(Platform):
    page: int = Field(default=200, gt=0)
    max_page: int = Field(default=200, gt=0)
    purge_batch: int = Field(default=1000, gt=0)


class NotificationsManagerImpl(NotificationsManagerInterface):
    def __init__(
        self,
        storage: NotificationStorageInterface,
        sessions: AgentSessionsManagerInterface,
        steps: StepsManagerInterface,
        tools: ToolsManagerInterface,
        tenancy: TenancyManagerInterface,
        intake: IntakeManagerInterface,
        integrations: Callable[[str], IntegrationInterface],
        options: NotificationsOptions,
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

    async def notify_park(self, ctx: TenantContext, run: LoopRun) -> tuple[Notification, ...]:
        ctx.require(Permission.WRITE)
        park = run.park
        if run.end is not RunEnd.PARKED or park is None or not needs_person(park):
            return ()
        session = await self._sessions.get_session(ctx, run.session_id)
        history = await self._history(ctx, session.id)
        parked = parked_step(history, park)
        if parked is None:
            # The session moved on from the park this run wrote.
            return ()
        members = await self._members(ctx)
        told: list[Notification] = []
        for ask in await self._asks(ctx, session, park, history, members):
            for recipient in ask.recipients:
                told.extend(await self._tell(ctx, session, park, parked, ask, recipient))
        return tuple(told)

    async def get_notifications(self, ctx: TenantContext, limit: int) -> tuple[Notification, ...]:
        ctx.require(Permission.READ)
        bounded = max(1, min(limit, self._options.max_page))
        return tuple(await self._storage.read_notifications(ctx.org_id, ctx.user_id, bounded))

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
        history: Sequence[Step],
        members: Sequence[Membership],
    ) -> list[Ask]:
        title = session.title
        if park.reason is ParkReason.PERSON and park.unlock == APPROVAL_UNLOCK:
            policy = await self._tools.get_policy(ctx)
            asks: list[Ask] = []
            for request in held_calls(history):
                header = request.header
                assert isinstance(header, ToolRequestHeader)
                roles = approver_roles(policy, header.authorization_class)
                asks.append(
                    Ask(
                        action="decide_call",
                        link=decision_link(session.id, request),
                        text=f"{title}: a call to {header.tool} waits for your decision.",
                        recipients=holding(members, roles),
                    )
                )
            return asks
        budget = as_budget(park.unlock) if park.reason is ParkReason.BUDGET else None
        if budget is not None:
            return [
                Ask(
                    action="raise_budget",
                    link=NO_ROUTE,
                    text=f"{title} waits for a raise of budget {budget}.",
                    recipients=holding_permission(members, SETS_BUDGETS),
                )
            ]
        if park.reason is ParkReason.BUDGET and park.unlock == FUNDS_UNLOCK:
            return [
                Ask(
                    action="top_up",
                    link=NO_ROUTE,
                    text=f"{title} waits for funds: the account is spent.",
                    recipients=holding_permission(members, SETS_BUDGETS),
                )
            ]
        if park.reason is ParkReason.PERSON and park.unlock == ANOMALY_UNLOCK:
            # The requester cannot clear it: approving a call past its
            # session's norm is billing's, and takes its permission.
            return [
                Ask(
                    action="approve_call",
                    link=NO_ROUTE,
                    text=(
                        f"{title}: a call costs far more than the session's others,"
                        " and waits for your approval."
                    ),
                    recipients=holding_permission(members, APPROVES_CALLS),
                )
            ]
        # Any other park on a person waits on the person who asked; one who
        # holds no place now leaves it to the people who manage the tenant.
        requester = session.speaker.id if session.speaker is not None else session.created_by
        held = {member.user_id for member in members}
        recipients = (
            (requester,)
            if requester in held
            else holding_permission(members, Permission.MANAGE_MEMBERS)
        )
        return [
            Ask(
                action=park.unlock,
                link=answer_link(session.id),
                text=f"{title} waits for you: {park.unlock}.",
                recipients=recipients,
            )
        ]

    async def _tell(
        self,
        ctx: TenantContext,
        session: AgentSession,
        park: Park,
        parked: Step,
        ask: Ask,
        recipient: UUID,
    ) -> list[Notification]:
        """One recipient on each of their channels: the platform's own list,
        and each account of theirs an integration holds. A post an
        integration cannot make now is left out, and the list still tells
        them."""
        channels = [(PORTAL, "")]
        for link in await self._intake.get_links(ctx, recipient):
            channels.append((link.integration, link.external_id))
        told: list[Notification] = []
        for channel, address in channels:
            notification_id_ = notification_id(parked, ask.action, ask.link, recipient, channel)
            held = await self._storage.read_notification(ctx.org_id, notification_id_)
            if held is not None:
                told.append(held)
                continue
            provenance: Provenance | None = None
            if channel != PORTAL:
                try:
                    posted = await self._integrations(channel).post(
                        address, f"{ask.text} {ask.link}" if ask.link else ask.text
                    )
                except InfraException:
                    log.warning(
                        "%s could not tell %s of session %s", channel, recipient, session.id
                    )
                    continue
                provenance = Provenance(posted.provenance)
            notification = Notification(
                id=notification_id_,
                created_at=self._clock(),
                recipient=recipient,
                session_id=session.id,
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
            await self._storage.create_notification(ctx.org_id, notification)
            told.append(notification)
        return told

    async def _history(self, ctx: TenantContext, session_id: UUID) -> list[Step]:
        steps: list[Step] = []
        while True:
            after = steps[-1].seq if steps else 0
            page = await self._steps.get_steps(ctx, session_id, after, self._options.page)
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
