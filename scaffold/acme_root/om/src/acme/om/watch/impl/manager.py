from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field, SecretStr

from acme.infra.agent_workspaces import Durability
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agent_steps.types.header import ParkReason
from acme.om.agent_workspaces import AgentWorkspacesManagerInterface
from acme.om.agent_workspaces.placed import PlacedWorkspacesInterface
from acme.om.agent_workspaces.types.snapshot import HostSnapshot
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.loop import LoopManagerInterface
from acme.om.agents.loop_rules import kept_snapshot
from acme.om.base import OmBase, derived_id, new_id, utcnow
from acme.om.change_events import ChangeEventsManagerInterface
from acme.om.change_events.manager import audit_change_event
from acme.om.context import Permission, RequestContext, TenantContext
from acme.om.exceptions import (
    Conflict,
    LeaseLost,
    NotAuthorized,
    NotFound,
    Unavailable,
    ValidationFailed,
)
from acme.om.exec_relay import ExecRelayManagerInterface
from acme.om.exec_relay.exceptions import NoWorkspaceHost
from acme.om.exec_relay.rules import exec_id, key_time, stale
from acme.om.exec_relay.types.exec import REQUESTS, ExecCall, ExecProgress, RunRequest
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.types.host import ClaimantIdentity
from acme.om.intake.rules import in_person
from acme.om.retention.crossing import CrossingKind, CrossingRefused
from acme.om.retention.crossing import verified as crossed
from acme.om.tools.rules import named_snapshot
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

TAKEN = "watch.control.taken"
SENT = "watch.command.sent"
GIVEN_BACK = "watch.control.given_back"


class WatchOptions(OmBase):
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
        steps: AgentStepsManagerInterface,
        exec_relay: ExecRelayManagerInterface,
        agent_workspaces: AgentWorkspacesManagerInterface,
        events: ChangeEventsManagerInterface,
        stream: StreamServiceInterface,
        options: WatchOptions,
        clock: Callable[[], datetime] = utcnow,
        *,
        hosts: HostsManagerInterface,
        work: WorkManagerInterface,
        kind_streams: KindStreamsInterface | None = None,
        placed: PlacedWorkspacesInterface | None = None,
    ) -> None:
        self._sessions = sessions
        self._agents = agents
        self._loop = loop
        self._steps = steps
        self._exec_relay = exec_relay
        self._agent_workspaces = agent_workspaces
        self._change_events = events
        self._stream = stream
        self._options = options
        self._clock = clock
        self._hosts = hosts
        self._work = work
        self._kind_streams = kind_streams
        self._placed = placed

    # The live read.

    async def open_live(self, ctx: TenantContext, agent_session_id: UUID) -> LiveRead:
        ctx.require(Permission.READ)
        await self._sessions.get_agent_session(ctx, agent_session_id)
        expires_at = self._clock() + self._options.live_read_life
        grant = Grant(
            agent_session_id=agent_session_id, viewer_id=ctx.user_id, expires_at=expires_at
        )
        handle = signed(self._key(), grant)
        return LiveRead(agent_session_id=agent_session_id, handle=handle, expires_at=expires_at)

    async def read_live(self, rctx: RequestContext, handle: str, seen: Sequence[Seen]) -> LivePage:
        grant = verified(self._key(), handle)
        if grant is None:
            raise LiveReadRefused("the handle is not one the platform signed")
        if self._clock() >= grant.expires_at:
            raise LiveReadRefused("the handle has expired; ask for a new one")
        streams = await self._stream.read(grant.agent_session_id, seen[:MAX_SEEN])
        return LivePage(agent_session_id=grant.agent_session_id, streams=streams)

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
        await streams.append(kind, item.id, appended.stream, entries, org_id=claimant.org_id)

    async def read_as(
        self,
        rctx: RequestContext,
        claimant: ClaimantIdentity,
        item_id: UUID,
        kind: str,
        claim_token: UUID,
        seen: Sequence[ItemSeen],
    ) -> ItemPage:
        streams = self._read_by(kind, claimant.kind)
        # Every item it does not hold is the same NotFound, placement's own:
        # another token, or a lapsed lease no sweep requeued yet, tells it
        # no more than another tenant's item does.
        missing = NotFound(f"{claimant.kind}:{claimant.id} holds no work item {item_id}")
        try:
            item = await self._hosts.held_as(rctx, claimant, item_id, claim_token)
        except LeaseLost:
            raise missing from None
        if item.lease_expires_at is None or item.lease_expires_at <= self._clock():
            raise missing
        return await _page(streams, kind, item.id, seen)

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
        return await _page(self._written(grant.kind), grant.kind, grant.item_id, seen)

    # Take control, give back.

    async def take_control(self, ctx: TenantContext, agent_session_id: UUID) -> AgentSession:
        await self._person(ctx, agent_session_id)
        session = await self._sessions.get_agent_session(ctx, agent_session_id)
        if session.park is None or session.park.reason is not ParkReason.HANDOVER:
            # Restored before it is handed over: a take whose restore fails
            # hands nothing over, and a workspace a person holds already is
            # never restored over their work.
            await self._restore_kept(ctx, agent_session_id)
            session = await self._loop.take_over(ctx, agent_session_id)
        elif session.park.holder not in (None, ctx.user_id):
            # A hand-over is its holder's: no one else takes it from them.
            raise Conflict(f"agent session {agent_session_id} is held by another person")
        cursor = await self._steps.get_cursor(ctx, agent_session_id)
        # What the agent's run still runs on the host stops now, so nothing of
        # its runs beside the person's commands; theirs run under this epoch.
        await self._exec_relay.interrupt_running(ctx, ctx.org_id, agent_session_id, cursor.epoch)
        await self._audit(ctx, new_id(), TAKEN, agent_session_id, {"epoch": cursor.epoch})
        return session

    async def _restore_kept(self, ctx: TenantContext, agent_session_id: UUID) -> None:
        """A workspace kept by snapshots, which a host holds, is restored from
        the latest snapshot its history names before the person's hands are
        on it, as its next run's would be: its instance may have gone since
        its run, and one started anew over its files alone would lack what
        its commands wrote outside them. The host that holds it replaces it
        from its store; the take waits for it a while, then fails with the
        reason, having handed nothing over, and a take again waits for the
        same restore. One that something touched since its last snapshot
        stands as it is."""
        try:
            pin = await self._agent_workspaces.get_workspace(ctx, agent_session_id)
        except NotFound:
            return
        if pin.durability is not Durability.SNAPSHOT:
            return
        latest = kept_snapshot(await self._history(ctx, agent_session_id))
        named = None if latest is None else named_snapshot(latest)
        if named is None:
            return
        record = await self._agent_workspaces.kept_snapshot(ctx, named.id)
        if self._placed is None or record is None or not record.on_host:
            return
        if record.hash != named.hash:
            return
        restore = HostSnapshot(
            id=record.id,
            reference=record.reference,
            digest=record.digest,
            size=record.size,
            kept_by=record.host_id,
        )
        await self._placed.held_on_host(ctx, agent_session_id, pin.spec(), restore)

    async def _history(self, ctx: TenantContext, agent_session_id: UUID) -> list[AgentStep]:
        steps: list[AgentStep] = []
        after = 0
        while True:
            page = await self._steps.get_agent_steps(ctx, agent_session_id, after, 500)
            steps.extend(page.items)
            if not page.has_more or not page.items:
                return steps
            after = page.items[-1].seq

    async def run_command(
        self, ctx: TenantContext, agent_session_id: UUID, command: HandCommand
    ) -> HandRun:
        await self._person(ctx, agent_session_id)
        # The epoch before the park: a giving back between the two either
        # clears the park this reads, or takes an epoch above this one, which
        # fences the command at its claim.
        cursor = await self._steps.get_cursor(ctx, agent_session_id)
        session = await self._sessions.get_agent_session(ctx, agent_session_id)
        if session.park is None or session.park.reason is not ParkReason.HANDOVER:
            raise NotHandedOver(
                f"the agent holds session {agent_session_id}'s workspace; take control first"
            )
        if session.park.holder not in (None, ctx.user_id):
            raise NotAuthorized(f"session {agent_session_id} is held by another person")
        if await self._exec_relay.binding_of(ctx, agent_session_id) is None:
            raise NoWorkspaceHost(f"no host holds session {agent_session_id}'s workspace")
        workspace = await self._agent_workspaces.get_workspace(ctx, agent_session_id)
        request = RunRequest(argv=command.argv, cwd=command.cwd)
        item_id = exec_id(command.key, REQUESTS.dump_json(request), 0)
        # Recorded as the person's before it is sent: no command runs that
        # its record does not name.
        facts: dict[str, object] = {
            "agent_session_id": str(agent_session_id),
            "key": str(command.key),
            "epoch": cursor.epoch,
        }
        audit_id = derived_id(item_id, key_time(command.key), "watch:command")
        await self._audit(ctx, audit_id, SENT, item_id, facts)
        call = ExecCall(
            agent_session_id=agent_session_id,
            key=command.key,
            request=request,
            effect="unsafe",
            deadline=self._clock() + timedelta(seconds=command.timeout_seconds),
            epoch=cursor.epoch,
            spec=workspace.spec(),
            by_person=True,
        )
        item = await self._exec_relay.send(ctx, ctx.org_id, call, 0)
        return HandRun(
            item_id=item.id,
            agent_session_id=agent_session_id,
            key=command.key,
            user_id=ctx.user_id,
            epoch=cursor.epoch,
            state=item.state,
        )

    async def command(
        self, ctx: TenantContext, agent_session_id: UUID, key: UUID, after_seq: int
    ) -> ExecProgress:
        ctx.require(Permission.READ)
        await self._sessions.get_agent_session(ctx, agent_session_id)
        cursor = await self._steps.get_cursor(ctx, agent_session_id)
        item = await self._exec_relay.outcome_of(
            ctx, ctx.org_id, agent_session_id, key, cursor.epoch
        )
        if item is None:
            raise NotFound(f"session {agent_session_id} sent no command under {key}")
        return await self._exec_relay.watch(ctx, ctx.org_id, item.id, after_seq)

    async def give_back(
        self, ctx: TenantContext, agent_session_id: UUID, summary: str, stop: bool = False
    ) -> AgentSession:
        await self._person(ctx, agent_session_id)
        session = await self._sessions.get_agent_session(ctx, agent_session_id)
        if session.park is not None and session.park.reason is ParkReason.HANDOVER:
            if session.park.holder not in (None, ctx.user_id):
                raise NotAuthorized(f"session {agent_session_id} is held by another person")
            cursor = await self._steps.get_cursor(ctx, agent_session_id)
            running = [
                item
                for item in await self._exec_relay.running(ctx, ctx.org_id, agent_session_id)
                if not stale(item.epoch, cursor.epoch)
            ]
            if running and not stop:
                raise CommandRunning(
                    f"a command of the person's still runs in session {agent_session_id}: "
                    "wait for it to end, or give back with stop"
                )
            if running:
                await self._exec_relay.interrupt_running(ctx, ctx.org_id, agent_session_id, None)
        session = await self._loop.give_back(ctx, agent_session_id, summary)
        cursor = await self._steps.get_cursor(ctx, agent_session_id)
        await self._audit(ctx, new_id(), GIVEN_BACK, agent_session_id, {"epoch": cursor.epoch})
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

    def _read_by(self, kind: str, claimant: str) -> KindStreamsInterface:
        """The product's streams, for a kind the claimant's own kind reads."""
        if self._kind_streams is None or self._kind_streams.reader(kind) != claimant:
            raise NotFound(f"no stream kind {kind} is read by {claimant}")
        return self._kind_streams

    def _key(self) -> bytes:
        key = self._options.live_read_key
        if key is None:
            raise Unavailable("no live-read key is configured: a live read is refused")
        return key.get_secret_value().encode()

    async def _person(self, ctx: TenantContext, agent_session_id: UUID) -> None:
        """A person at the product surface themselves, who may write and may
        instruct the session: their hands, never an agent's call or a
        program's key."""
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("control is taken by a person, in person")
        await self._sessions.get_agent_session(ctx, agent_session_id)
        await self._agents.require_instructor(ctx, agent_session_id)

    async def _audit(
        self, ctx: TenantContext, event_id: UUID, kind: str, target: UUID, facts: dict[str, object]
    ) -> None:
        await self._change_events.append_change_event(
            ctx, audit_change_event(ctx, event_id, kind, target, facts)
        )


async def _page(
    streams: KindStreamsInterface, kind: str, item_id: UUID, seen: Sequence[ItemSeen]
) -> ItemPage:
    """The item's open streams of the kind, each from the entry after the
    last `seen` names for it, and whether entries it never read went."""
    after = {mark.stream: mark.n for mark in seen[:MAX_SEEN]}
    slices = await streams.read(kind, item_id, after)
    return ItemPage(
        item_id=item_id,
        kind=kind,
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
