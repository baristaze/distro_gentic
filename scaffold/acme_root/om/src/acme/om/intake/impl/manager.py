from collections.abc import Callable, Sequence
from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.integrations.events import IntegrationInterface
from acme.integrations.exceptions import DeliveryRefused
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.loop import LoopManagerInterface
from acme.om.attribution import PrincipalContext
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import Platform, derived_id, new_id, utcnow
from acme.om.context import Permission, RequestContext, TenantContext
from acme.om.events import EventsManagerInterface
from acme.om.events.manager import audit_event
from acme.om.exceptions import Conflict, NotAuthorized, NotFound, ValidationFailed
from acme.om.intake.manager import IntakeManagerInterface
from acme.om.intake.rules import DELIVERED, Facts, effect_of, in_person, input_step
from acme.om.intake.storage import IntakeStorageInterface
from acme.om.intake.types.event import AuthorKind, ChatApproval, FeedbackEvent
from acme.om.intake.types.link import (
    AccountLink,
    HandleKind,
    Installation,
    PlatformAct,
    WorkBinding,
)
from acme.om.intake.types.route import Effect, Routed
from acme.om.steps.types.header import ParkReason
from acme.om.steps.types.step import Step
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tools.manager import ToolsManagerInterface

ROUTED = "intake.event.routed"
CONNECTED = "intake.installation.created"
UNLINKED = "intake.account_link.deleted"
APPROVED = "intake.chat_approval.decided"
REFUSED = "intake.chat_approval.refused"


class IntakeOptions(Platform):
    # The most rows of each kind one purge call takes.
    purge_batch: int = Field(default=1000, gt=0)
    # The most accounts one read of a user's links answers.
    links: int = Field(default=50, gt=0)


class IntakeManagerImpl(IntakeManagerInterface):
    def __init__(
        self,
        storage: IntakeStorageInterface,
        sessions: AgentSessionsManagerInterface,
        agents: AgentsManagerInterface,
        loop: LoopManagerInterface,
        tools: ToolsManagerInterface,
        events: EventsManagerInterface,
        tenancy: TenancyManagerInterface,
        principal_context: PrincipalContext,
        integrations: Callable[[str], IntegrationInterface],
        options: IntakeOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._integrations = integrations
        self._sessions = sessions
        self._agents = agents
        self._loop = loop
        self._tools = tools
        self._events = events
        self._tenancy = tenancy
        self._live = principal_context
        self._options = options
        self._clock = clock

    async def connect_installation(
        self, ctx: TenantContext, integration: str, grant: str
    ) -> Installation:
        ctx.require(Permission.MANAGE_MEMBERS)
        if not in_person(ctx):
            raise NotAuthorized("an installation is connected by a person, in person")
        try:
            named = self._integrations(integration).verify_installation(grant, self._clock())
        except DeliveryRefused as refused:
            raise ValidationFailed(f"the {integration} grant: {refused.message}") from None
        installation = Installation(
            id=new_id(),
            created_at=self._clock(),
            integration=integration,
            installation=named,
            created_by=ctx.user_id,
        )
        held = await self._storage.create_installation(ctx.org_id, installation)
        if held is None:
            raise Conflict(f"{integration} installation {named} is another tenant's")
        if held.id == installation.id:
            await self._audit(ctx, CONNECTED, held.id, {"integration": integration})
        return held

    async def tenant_of(
        self, rctx: RequestContext, integration: str, installation: str
    ) -> UUID | None:
        return await self._storage.read_installation_org(integration, installation)

    async def link_account(
        self, ctx: TenantContext, integration: str, external_id: str, user_id: UUID
    ) -> AccountLink:
        ctx.require(Permission.MANAGE_MEMBERS)
        if not in_person(ctx):
            raise NotAuthorized("an account is linked by a person, never by an agent's call")
        link = AccountLink(
            id=new_id(),
            created_at=self._clock(),
            integration=integration,
            external_id=external_id,
            user_id=user_id,
            created_by=ctx.user_id,
        )
        held = await self._storage.create_link(ctx.org_id, link)
        if held.user_id != user_id:
            raise Conflict(f"{integration} account {external_id} is linked to another user")
        return held

    async def unlink_account(self, ctx: TenantContext, integration: str, external_id: str) -> None:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("an account is unlinked by a person, never by an agent's call")
        link = await self._storage.read_link(ctx.org_id, integration, external_id)
        if link is None:
            raise NotFound(f"{integration} account {external_id} is linked to no user")
        if link.user_id != ctx.user_id:
            ctx.require(Permission.MANAGE_MEMBERS)
        if await self._storage.delete_link(ctx.org_id, integration, external_id):
            facts: dict[str, object] = {"integration": integration, "user_id": str(link.user_id)}
            await self._audit(ctx, UNLINKED, link.id, facts)

    async def get_links(self, ctx: TenantContext, user_id: UUID) -> tuple[AccountLink, ...]:
        ctx.require(Permission.READ)
        return tuple(await self._storage.read_user_links(ctx.org_id, user_id, self._options.links))

    async def bind_work(
        self, ctx: TenantContext, session_id: UUID, kind: HandleKind, handle: str
    ) -> WorkBinding:
        ctx.require(Permission.WRITE)
        await self._sessions.get_session(ctx, session_id)
        binding = WorkBinding(
            id=new_id(), created_at=self._clock(), session_id=session_id, kind=kind, handle=handle
        )
        held = await self._storage.create_binding(ctx.org_id, binding)
        if held.session_id != session_id:
            raise Conflict(f"{kind.value} {handle} is another session's work")
        return held

    async def record_act(
        self, ctx: TenantContext, session_id: UUID, integration: str, refs: Sequence[str]
    ) -> None:
        ctx.require(Permission.WRITE)
        await self._sessions.get_session(ctx, session_id)
        now = self._clock()
        for ref in refs:
            act = PlatformAct(
                id=new_id(), created_at=now, integration=integration, ref=ref, session_id=session_id
            )
            await self._storage.record_act(ctx.org_id, act)

    async def route(self, ctx: TenantContext, event: FeedbackEvent) -> Routed:
        ctx.require(Permission.WRITE)
        session = await self._find(ctx, event)
        # The cause follows the act the event names, not the session it
        # reaches: every session acts through the one platform account.
        act = None
        if event.refs:
            act = await self._storage.read_act(ctx.org_id, event.integration, event.refs)
        routed = Routed(
            event_id=event.id,
            integration=event.integration,
            provenance=event.provenance,
            arrival=event.arrival.value,
            effect=Effect.UNROUTED,
        )
        if session is not None:
            routed = await self._deliver(ctx, event, session)
        # With no act recorded, an event on a session's own work (its id,
        # its pull request, its branch) follows from that session, as a
        # check on its branch follows from its push.
        cause = act.session_id if act is not None else None
        if cause is None and session is not None:
            cause = session.id
        routed = routed.model_copy(
            update={
                "caused_by": cause,
                "platform": event.author.kind is AuthorKind.PLATFORM,
            }
        )
        entry = audit_event(
            ctx,
            derived_id(event.id, event.occurred_at, "intake:routed"),
            ROUTED,
            event.id,
            routed.model_dump(mode="json"),
        )
        stored = await self._events.append_event(ctx, entry)
        # A redelivery meets the entry the first routing wrote, and answers it.
        return Routed.model_validate(stored.payload)

    async def approve_from_chat(self, ctx: TenantContext, approval: ChatApproval) -> Step:
        ctx.require(Permission.WRITE)
        member = await self._mapped(ctx, approval.integration, approval.external_id)
        facts = approval.model_dump(mode="json", exclude={"note"})
        if member is None:
            await self._audit(ctx, REFUSED, approval.session_id, facts)
            raise NotAuthorized(
                f"{approval.integration} account {approval.external_id} maps to no user"
            )
        try:
            decided = await self._tools.decide_call(
                member,
                approval.session_id,
                approval.request_seq,
                approve=approval.approve,
                note=approval.note,
            )
        except NotAuthorized:
            await self._audit(member, REFUSED, approval.session_id, facts)
            raise
        # Audited as the mapped user: the entry's actor is theirs.
        await self._audit(member, APPROVED, approval.session_id, facts)
        return decided

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    # Helpers.

    async def _find(self, ctx: TenantContext, event: FeedbackEvent) -> AgentSession | None:
        """The session the event names: by its id, else its pull request,
        else its branch. One the tenant does not hold is none."""
        names = event.names
        session_id = names.session_id
        if session_id is None and names.pull_request is not None:
            bound = await self._storage.read_binding(
                ctx.org_id, HandleKind.PULL_REQUEST, names.pull_request
            )
            session_id = None if bound is None else bound.session_id
        if session_id is None and names.branch is not None:
            bound = await self._storage.read_binding(ctx.org_id, HandleKind.BRANCH, names.branch)
            session_id = None if bound is None else bound.session_id
        if session_id is None:
            return None
        try:
            return await self._sessions.get_session(ctx, session_id)
        except NotFound:
            return None

    async def _deliver(
        self, ctx: TenantContext, event: FeedbackEvent, session: AgentSession
    ) -> Routed:
        member: TenantContext | None = None
        if event.author.kind is AuthorKind.PERSON:
            member = await self._mapped(ctx, event.integration, event.author.external_id)
        instructs = member is not None and await self._may_instruct(member, session.id)
        facts = Facts(
            arrival=event.arrival,
            author=event.author.kind,
            check=event.check,
            archived=session.archived_at is not None,
            instructs=instructs,
        )
        effect = effect_of(facts)
        routed = Routed(
            event_id=event.id,
            integration=event.integration,
            provenance=event.provenance,
            arrival=event.arrival.value,
            effect=effect,
            session_id=session.id,
        )
        if effect is Effect.HAND_OVER:
            # The agent stands down, whoever pushed: its loop parks on a
            # hand-over only a person's giving back clears. The router takes
            # it, since a pusher may hold no place, or no write, here. Parked
            # on one already, it stays.
            if session.park is None or session.park.reason is not ParkReason.HANDOVER:
                await self._loop.take_over(ctx, session.id)
            pusher = None if member is None else member.user_id
            return routed.model_copy(update={"principal_id": pusher})
        if effect not in DELIVERED:
            return routed
        speaker = member if effect is Effect.WAKE and member is not None else ctx
        principal = Principal(
            kind=PrincipalKind.PERSON if speaker is member else PrincipalKind.SERVICE,
            id=speaker.user_id,
        )
        step = input_step(event, session.id, effect, principal, self._clock())
        (stored,), _ = await self._sessions.receive(speaker, session.id, [step])
        return routed.model_copy(
            update={
                "step_id": stored.id,
                "principal_id": speaker.user_id if speaker is member else None,
            }
        )

    async def _mapped(
        self, ctx: TenantContext, integration: str, external_id: str
    ) -> TenantContext | None:
        """The live context of the user an outside account maps to, read now:
        none for an account with no link, or a user who holds no place in the
        tenant any more."""
        link = await self._storage.read_link(ctx.org_id, integration, external_id)
        if link is None:
            return None
        try:
            return await self._live(
                ctx, ctx.org_id, Principal(kind=PrincipalKind.PERSON, id=link.user_id)
            )
        except NotAuthorized:
            return None

    async def _may_instruct(self, member: TenantContext, session_id: UUID) -> bool:
        try:
            await self._agents.require_instructor(member, session_id)
        except NotAuthorized:
            return False
        return True

    async def _audit(
        self, ctx: TenantContext, kind: str, target: UUID, facts: dict[str, object]
    ) -> None:
        await self._events.append_event(ctx, audit_event(ctx, new_id(), kind, target, facts))
