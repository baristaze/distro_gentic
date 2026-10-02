from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agents import AgentsManagerInterface
from acme.om.base import Platform, derived_id, new_id, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import Conflict, NotAuthorized, NotFound, UniqueKeyTaken
from acme.om.intake.rules import in_person
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import versioned_row
from acme.om.playbooks.manager import PlaybooksManagerInterface
from acme.om.playbooks.rules import skill_md
from acme.om.playbooks.storage import PlaybookStorageInterface
from acme.om.playbooks.types.playbook import (
    Playbook,
    PlaybookDraft,
    PlaybookGate,
    PlaybookInvocation,
)
from acme.om.steps.rules import message_step
from acme.om.tenancy import TenancyManagerInterface

PUBLISHED = "playbooks.playbook.created"


class PlaybooksOptions(Platform):
    # The most playbooks one session's gates are read from.
    per_session: int = Field(default=50, gt=0)
    purge_batch: int = Field(default=1000, gt=0)


class PlaybooksManagerImpl(PlaybooksManagerInterface):
    def __init__(
        self,
        storage: PlaybookStorageInterface,
        sessions: AgentSessionsManagerInterface,
        agents: AgentsManagerInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        options: PlaybooksOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._sessions = sessions
        self._agents = agents
        self._tenancy = tenancy
        self._relay = relay
        self._options = options
        self._clock = clock

    async def publish(self, ctx: TenantContext, draft: PlaybookDraft) -> Playbook:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("a playbook is published by a person, never by an agent's call")
        latest = await self._storage.read_latest(ctx.org_id, draft.name)
        playbook = Playbook(
            id=new_id(),
            created_at=self._clock(),
            name=draft.name,
            version=1 if latest is None else latest.version + 1,
            description=draft.description,
            body=draft.body,
            gates=draft.gates,
            published_by=ctx.user_id,
        )
        rows = (versioned_row(ctx, PUBLISHED, playbook.id, playbook.version),)
        try:
            await self._storage.create_playbook(ctx.org_id, playbook, rows)
        except UniqueKeyTaken as taken:
            raise Conflict(f"playbook {draft.name} was published meanwhile") from taken
        await self._relay.relay_all(ctx.org_id, rows)
        return playbook

    async def get_playbook(self, ctx: TenantContext, name: str) -> Playbook:
        ctx.require(Permission.READ)
        found = await self._storage.read_latest(ctx.org_id, name)
        if found is None:
            raise NotFound(f"playbook {name} not found")
        return found

    async def invoke(self, ctx: TenantContext, session_id: UUID, name: str) -> PlaybookInvocation:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("a playbook is invoked by a principal, never by an agent's call")
        await self._agents.require_instructor(ctx, session_id)
        playbook = await self.get_playbook(ctx, name)
        invocation = await self._storage.create_invocation(
            ctx.org_id,
            PlaybookInvocation(
                id=new_id(),
                created_at=self._clock(),
                session_id=session_id,
                playbook_id=playbook.id,
                name=playbook.name,
                version=playbook.version,
                invoked_by=ctx.user_id,
            ),
        )
        # The brief is the caller's word: one message an invocation, so a
        # second invocation of the version sends nothing new.
        brief = message_step(
            derived_id(invocation.id, invocation.created_at, "playbook"),
            self._clock(),
            session_id,
            ctx,
            skill_md(playbook),
        )
        await self._sessions.receive(ctx, session_id, [brief])
        return invocation

    async def gates_of(self, ctx: TenantContext, session_id: UUID) -> tuple[PlaybookGate, ...]:
        ctx.require(Permission.READ)
        gates: list[PlaybookGate] = []
        invocations = await self._storage.read_invocations(
            ctx.org_id, session_id, self._options.per_session
        )
        for invocation in invocations:
            playbook = await self._storage.read_playbook(ctx.org_id, invocation.playbook_id)
            if playbook is not None:
                gates.extend(playbook.gates)
        return tuple(gates)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)
