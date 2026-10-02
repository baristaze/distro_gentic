from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field, SecretStr

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.loop import LoopManagerInterface
from acme.om.base import Platform, derived_id, new_id, utcnow
from acme.om.context import Permission, RequestContext, TenantContext
from acme.om.events import EventsManagerInterface
from acme.om.events.manager import audit_event
from acme.om.exceptions import NotAuthorized, NotFound, Unavailable
from acme.om.intake.rules import in_person
from acme.om.relay import RelayManagerInterface
from acme.om.relay.exceptions import NoWorkspaceHost
from acme.om.relay.rules import exec_id, key_time
from acme.om.relay.types.exec import REQUESTS, ExecCall, ExecProgress, RunRequest
from acme.om.steps import StepsManagerInterface
from acme.om.steps.types.header import ParkReason
from acme.om.watch.exceptions import LiveReadRefused, NotHandedOver
from acme.om.watch.manager import WatchManagerInterface
from acme.om.watch.rules import signed, verified
from acme.om.watch.stream import StreamServiceInterface
from acme.om.watch.types.control import HandCommand, HandRun
from acme.om.watch.types.live import MAX_SEEN, Grant, LivePage, LiveRead, Seen
from acme.om.workspaces import WorkspacesManagerInterface

TAKEN = "watch.control.taken"
SENT = "watch.command.sent"
GIVEN_BACK = "watch.control.given_back"


class WatchOptions(Platform):
    # The key live-read handles are signed with, shared by every process
    # that issues or reads one. None refuses every live read, and says so.
    live_read_key: SecretStr | None = None
    # How long a handle reads before its viewer asks for a new one.
    live_read_life: timedelta = Field(default=timedelta(minutes=5), gt=timedelta(0))


class WatchManagerImpl(WatchManagerInterface):
    def __init__(
        self,
        sessions: AgentSessionsManagerInterface,
        agents: AgentsManagerInterface,
        loop: LoopManagerInterface,
        steps: StepsManagerInterface,
        relay: RelayManagerInterface,
        workspaces: WorkspacesManagerInterface,
        events: EventsManagerInterface,
        stream: StreamServiceInterface,
        options: WatchOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._sessions = sessions
        self._agents = agents
        self._loop = loop
        self._steps = steps
        self._relay = relay
        self._workspaces = workspaces
        self._events = events
        self._stream = stream
        self._options = options
        self._clock = clock

    # The live read.

    async def open_live(self, ctx: TenantContext, session_id: UUID) -> LiveRead:
        ctx.require(Permission.READ)
        await self._sessions.get_session(ctx, session_id)
        expires_at = self._clock() + self._options.live_read_life
        grant = Grant(
            org_id=ctx.org_id, session_id=session_id, viewer_id=ctx.user_id, expires_at=expires_at
        )
        handle = signed(self._key(), grant)
        return LiveRead(session_id=session_id, handle=handle, expires_at=expires_at)

    async def read_live(self, rctx: RequestContext, handle: str, seen: Sequence[Seen]) -> LivePage:
        grant = verified(self._key(), handle)
        if grant is None:
            raise LiveReadRefused("the handle is not one the platform signed")
        if self._clock() >= grant.expires_at:
            raise LiveReadRefused("the handle has expired; ask for a new one")
        streams = self._stream.read(grant.session_id, seen[:MAX_SEEN])
        return LivePage(session_id=grant.session_id, streams=streams)

    # Take control, give back.

    async def take_control(self, ctx: TenantContext, session_id: UUID) -> AgentSession:
        await self._person(ctx, session_id)
        session = await self._sessions.get_session(ctx, session_id)
        if session.park is None or session.park.reason is not ParkReason.HANDOVER:
            session = await self._loop.take_over(ctx, session_id)
        cursor = await self._steps.get_cursor(ctx, session_id)
        await self._audit(ctx, new_id(), TAKEN, session_id, {"epoch": cursor.epoch})
        return session

    async def run_command(
        self, ctx: TenantContext, session_id: UUID, command: HandCommand
    ) -> HandRun:
        await self._person(ctx, session_id)
        # The epoch before the park: a giving back between the two either
        # clears the park this reads, or takes an epoch above this one, which
        # fences the command at its claim.
        cursor = await self._steps.get_cursor(ctx, session_id)
        session = await self._sessions.get_session(ctx, session_id)
        if session.park is None or session.park.reason is not ParkReason.HANDOVER:
            raise NotHandedOver(
                f"the agent holds session {session_id}'s workspace; take control first"
            )
        if await self._relay.binding_of(ctx, session_id) is None:
            raise NoWorkspaceHost(f"no host holds session {session_id}'s workspace")
        workspace = await self._workspaces.get_workspace(ctx, session_id)
        request = RunRequest(argv=command.argv, cwd=command.cwd)
        item_id = exec_id(command.key, REQUESTS.dump_json(request), 0)
        # Recorded as the person's before it is sent: no command runs that
        # its record does not name.
        facts: dict[str, object] = {
            "session_id": str(session_id),
            "key": str(command.key),
            "epoch": cursor.epoch,
        }
        audit_id = derived_id(item_id, key_time(command.key), "watch:command")
        await self._audit(ctx, audit_id, SENT, item_id, facts)
        call = ExecCall(
            session_id=session_id,
            key=command.key,
            request=request,
            effect="unsafe",
            deadline=self._clock() + timedelta(seconds=command.timeout_seconds),
            epoch=cursor.epoch,
            spec=workspace.spec(),
        )
        item = await self._relay.send(ctx, ctx.org_id, call, 0)
        return HandRun(
            item_id=item.id,
            session_id=session_id,
            key=command.key,
            user_id=ctx.user_id,
            epoch=cursor.epoch,
            state=item.state,
        )

    async def command(
        self, ctx: TenantContext, session_id: UUID, key: UUID, after_seq: int
    ) -> ExecProgress:
        ctx.require(Permission.READ)
        await self._sessions.get_session(ctx, session_id)
        cursor = await self._steps.get_cursor(ctx, session_id)
        item = await self._relay.outcome_of(ctx, ctx.org_id, session_id, key, cursor.epoch)
        if item is None:
            raise NotFound(f"session {session_id} sent no command under {key}")
        return await self._relay.watch(ctx, ctx.org_id, item.id, after_seq)

    async def give_back(self, ctx: TenantContext, session_id: UUID, summary: str) -> AgentSession:
        await self._person(ctx, session_id)
        session = await self._loop.give_back(ctx, session_id, summary)
        cursor = await self._steps.get_cursor(ctx, session_id)
        await self._audit(ctx, new_id(), GIVEN_BACK, session_id, {"epoch": cursor.epoch})
        return session

    # Helpers.

    def _key(self) -> bytes:
        key = self._options.live_read_key
        if key is None:
            raise Unavailable("no live-read key is configured: a live read is refused")
        return key.get_secret_value().encode()

    async def _person(self, ctx: TenantContext, session_id: UUID) -> None:
        """A person at the product surface themselves, who may write and may
        instruct the session: their hands, never an agent's call or a
        program's key."""
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("control is taken by a person, in person")
        await self._sessions.get_session(ctx, session_id)
        await self._agents.require_instructor(ctx, session_id)

    async def _audit(
        self, ctx: TenantContext, event_id: UUID, kind: str, target: UUID, facts: dict[str, object]
    ) -> None:
        await self._events.append_event(ctx, audit_event(ctx, event_id, kind, target, facts))
