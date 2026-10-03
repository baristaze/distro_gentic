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
from acme.om.exceptions import LeaseLost, NotAuthorized, NotFound, Unavailable, ValidationFailed
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.types.host import ClaimantIdentity
from acme.om.intake.rules import in_person
from acme.om.relay import RelayManagerInterface
from acme.om.relay.exceptions import NoWorkspaceHost
from acme.om.relay.rules import exec_id, key_time, stale
from acme.om.relay.types.exec import REQUESTS, ExecCall, ExecProgress, RunRequest
from acme.om.retention.crossing import CrossingKind, CrossingRefused
from acme.om.retention.crossing import verified as crossed
from acme.om.steps import StepsManagerInterface
from acme.om.steps.types.header import ParkReason
from acme.om.watch.exceptions import CommandRunning, LiveReadRefused, NotHandedOver
from acme.om.watch.kinds import MAX_APPEND_BYTES, MAX_APPEND_ENTRIES, KindStreamsInterface
from acme.om.watch.manager import WatchManagerInterface
from acme.om.watch.rules import signed, verified, verified_item
from acme.om.watch.stream import StreamServiceInterface
from acme.om.watch.types.control import HandCommand, HandRun
from acme.om.watch.types.live import (
    MAX_SEEN,
    Appended,
    Entry,
    Grant,
    ItemGrant,
    ItemPage,
    ItemRead,
    ItemSeen,
    ItemStream,
    LivePage,
    LiveRead,
    Seen,
)
from acme.om.work import WorkManagerInterface
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
        *,
        hosts: HostsManagerInterface,
        work: WorkManagerInterface,
        kind_streams: KindStreamsInterface | None = None,
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
        self._hosts = hosts
        self._work = work
        self._kind_streams = kind_streams

    # The live read.

    async def open_live(self, ctx: TenantContext, session_id: UUID) -> LiveRead:
        ctx.require(Permission.READ)
        await self._sessions.get_session(ctx, session_id)
        expires_at = self._clock() + self._options.live_read_life
        grant = Grant(session_id=session_id, viewer_id=ctx.user_id, expires_at=expires_at)
        handle = signed(self._key(), grant)
        return LiveRead(session_id=session_id, handle=handle, expires_at=expires_at)

    async def read_live(self, rctx: RequestContext, handle: str, seen: Sequence[Seen]) -> LivePage:
        grant = verified(self._key(), handle)
        if grant is None:
            raise LiveReadRefused("the handle is not one the platform signed")
        if self._clock() >= grant.expires_at:
            raise LiveReadRefused("the handle has expired; ask for a new one")
        streams = await self._stream.read(grant.session_id, seen[:MAX_SEEN])
        return LivePage(session_id=grant.session_id, streams=streams)

    # A product's streams, by the item a claimant holds.

    async def append_as(
        self,
        rctx: RequestContext,
        claimant: ClaimantIdentity,
        item_id: UUID,
        kind: str,
        appended: Appended,
    ) -> None:
        streams = self._written_by(kind, claimant.kind)
        if len(appended.entries) > MAX_APPEND_ENTRIES:
            raise ValidationFailed(f"an append carries at most {MAX_APPEND_ENTRIES} entries")
        if sum(len(entry.data) for entry in appended.entries) > MAX_APPEND_BYTES:
            raise ValidationFailed(f"an append carries at most {MAX_APPEND_BYTES} bytes")
        # Each entry's bytes are checked against their hash before anything
        # reads them, as a host's part is, so one that does not match lands
        # nothing of the append.
        for entry in appended.entries:
            if entry.crossing.kind is not CrossingKind.STREAM_PART:
                raise CrossingRefused(f"a {entry.crossing.kind.value} sent as a stream_part")
            crossed(entry.crossing, entry.data)
        item = await self._hosts.held_as(rctx, claimant, item_id, appended.claim_token)
        # A lease that lapsed is no longer held, though no sweep requeued
        # the item yet: the claimant renews it before it writes again.
        if item.lease_expires_at is None or item.lease_expires_at <= self._clock():
            raise LeaseLost(f"{claimant.kind} {claimant.id} no longer holds work item {item_id}")
        entries = [(entry.n, entry.data) for entry in appended.entries]
        await streams.append(kind, item.id, appended.stream, entries)

    async def open_item_live(self, ctx: TenantContext, item_id: UUID, kind: str) -> ItemRead:
        ctx.require(Permission.READ)
        self._written(kind)
        await self._work.get_item(ctx, item_id)
        expires_at = self._clock() + self._options.live_read_life
        grant = ItemGrant(item_id=item_id, kind=kind, viewer_id=ctx.user_id, expires_at=expires_at)
        handle = signed(self._key(), grant)
        return ItemRead(item_id=item_id, kind=kind, handle=handle, expires_at=expires_at)

    async def read_item_live(
        self, rctx: RequestContext, handle: str, seen: Sequence[ItemSeen]
    ) -> ItemPage:
        grant = verified_item(self._key(), handle)
        if grant is None:
            raise LiveReadRefused("the handle is not one the platform signed for an item")
        if self._clock() >= grant.expires_at:
            raise LiveReadRefused("the handle has expired; ask for a new one")
        after = {mark.stream: mark.n for mark in seen[:MAX_SEEN]}
        slices = await self._written(grant.kind).read(grant.kind, grant.item_id, after)
        return ItemPage(
            item_id=grant.item_id,
            kind=grant.kind,
            streams=tuple(
                ItemStream(
                    stream=held.stream,
                    first=held.first,
                    entries=tuple(Entry(n=n, data=data) for n, data in held.entries),
                    dropped=after.get(held.stream, -1) + 1 < held.first,
                )
                for held in slices
            ),
        )

    # Take control, give back.

    async def take_control(self, ctx: TenantContext, session_id: UUID) -> AgentSession:
        await self._person(ctx, session_id)
        session = await self._sessions.get_session(ctx, session_id)
        if session.park is None or session.park.reason is not ParkReason.HANDOVER:
            session = await self._loop.take_over(ctx, session_id)
        cursor = await self._steps.get_cursor(ctx, session_id)
        # What the agent's run still runs on the host stops now, so nothing of
        # its runs beside the person's commands; theirs run under this epoch.
        await self._relay.interrupt_running(ctx, ctx.org_id, session_id, cursor.epoch)
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
            by_person=True,
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

    async def give_back(
        self, ctx: TenantContext, session_id: UUID, summary: str, stop: bool = False
    ) -> AgentSession:
        await self._person(ctx, session_id)
        session = await self._sessions.get_session(ctx, session_id)
        if session.park is not None and session.park.reason is ParkReason.HANDOVER:
            cursor = await self._steps.get_cursor(ctx, session_id)
            running = [
                item
                for item in await self._relay.running(ctx, ctx.org_id, session_id)
                if not stale(item.epoch, cursor.epoch)
            ]
            if running and not stop:
                raise CommandRunning(
                    f"a command of the person's still runs in session {session_id}: "
                    "wait for it to end, or give back with stop"
                )
            if running:
                await self._relay.interrupt_running(ctx, ctx.org_id, session_id, None)
        session = await self._loop.give_back(ctx, session_id, summary)
        cursor = await self._steps.get_cursor(ctx, session_id)
        await self._audit(ctx, new_id(), GIVEN_BACK, session_id, {"epoch": cursor.epoch})
        return session

    # Helpers.

    def _written(self, kind: str) -> KindStreamsInterface:
        """The product's streams, for a kind a claimant writes; any other is
        not found."""
        if self._kind_streams is None or self._kind_streams.writer(kind) is None:
            raise NotFound(f"no stream kind {kind} is written by a claimant")
        return self._kind_streams

    def _written_by(self, kind: str, claimant: str) -> KindStreamsInterface:
        """The product's streams, for a kind the claimant's own kind writes."""
        if self._kind_streams is None or self._kind_streams.writer(kind) != claimant:
            raise NotFound(f"no stream kind {kind} is written by {claimant}")
        return self._kind_streams

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
