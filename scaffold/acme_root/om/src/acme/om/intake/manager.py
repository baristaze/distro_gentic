"""The intake swimlane: where the world's events reach a session. An event
from outside finds its session by the session id, the pull request, or the
branch it names, and the routing table decides what it does there: wake
the session, wait in its inbox, hand it over, or only be recorded. Only a
mapped user who may instruct the session speaks to it as a principal;
everything else arrives as data. A chat approval counts only as a mapped
user's."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from acme.om.context import TenantContext
from acme.om.intake.types.event import ChatApproval, FeedbackEvent
from acme.om.intake.types.link import AccountLink, HandleKind, WorkBinding
from acme.om.intake.types.route import Routed
from acme.om.steps.types.step import Step


class IntakeManagerInterface(ABC):
    @abstractmethod
    async def link_account(
        self, ctx: TenantContext, integration: str, external_id: str, user_id: UUID
    ) -> AccountLink:
        """Maps an outside account to a user of the tenant, as a person who
        manages its members may, in person: a context an agent's call runs
        under is `NotAuthorized`. One link an account: linked already, the
        link held answers, and one held for another user is `Conflict`."""
        ...

    @abstractmethod
    async def unlink_account(self, ctx: TenantContext, integration: str, external_id: str) -> None:
        """The account's link to its user gone, in person, by that user or by
        a person who manages the tenant's members: a context an agent's call
        runs under, or anyone else, is `NotAuthorized`. The account then
        speaks to no session as a principal and approves no call. An account
        with no link is `NotFound`."""
        ...

    @abstractmethod
    async def get_links(self, ctx: TenantContext, user_id: UUID) -> tuple[AccountLink, ...]:
        """The accounts linked to a user of the tenant: the channels the
        platform reaches them on beside its own."""
        ...

    @abstractmethod
    async def bind_work(
        self, ctx: TenantContext, session_id: UUID, kind: HandleKind, handle: str
    ) -> WorkBinding:
        """Records that a pull request or a branch is the session's work, so
        the events that name it find the session. One session a handle: one
        bound to another session is `Conflict`. A session the tenant does not
        hold is `NotFound`."""
        ...

    @abstractmethod
    async def record_act(
        self, ctx: TenantContext, session_id: UUID, integration: str, refs: Sequence[str]
    ) -> None:
        """Records an act a session made through the platform's account, by
        the integration's names for what it made (a comment's id, a commit),
        so an event that is or follows from it names the session it came
        from, whatever session that event reaches. The tool that acts calls
        it before it acts. A session the tenant does not hold is
        `NotFound`."""
        ...

    @abstractmethod
    async def route(self, ctx: TenantContext, event: FeedbackEvent) -> Routed:
        """Places an event, under the tenant's service context: finds its
        session, gives it its effect by the routing table, and delivers it.
        A principal's message is appended under the mapped user's live
        context; any other input is an event, data under the router's own
        principal. A person's push hands the session over. The event's cause
        is the session whose recorded act it names, wherever it routes, and
        else the session whose work it lands on. Every
        event is audited once with what it did, and a redelivery changes
        nothing."""
        ...

    @abstractmethod
    async def approve_from_chat(self, ctx: TenantContext, approval: ChatApproval) -> Step:
        """A person's decision on a call, clicked in chat: it counts only when
        the chat account maps to a user of the tenant whose role may decide
        the call's class, and it is decided, and audited, as that user. An
        account with no link, or a user who may not decide it, is
        `NotAuthorized`, audited as refused, with nothing decided."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its links and its
        bindings, a batch at most a call. Any other tenant returns 0."""
        ...
