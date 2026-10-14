from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.agent_playbooks.manager import AgentPlaybooksManagerInterface
from acme.om.agent_playbooks.rules import skill_md
from acme.om.agent_playbooks.storage import AgentPlaybookStorageInterface
from acme.om.agent_playbooks.types.agent_playbook import (
    AgentPlaybook,
    AgentPlaybookDraft,
    AgentPlaybookGate,
    AgentPlaybookInvocation,
    AgentPlaybookPin,
)
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.storage import AgentSessionStorageInterface
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.kind import AgentKindCatalog
from acme.om.agents.types.request import MAX_STANDING
from acme.om.base import Platform, derived_id, new_id, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import (
    Conflict,
    NotAuthorized,
    NotFound,
    TenantMismatch,
    UniqueKeyTaken,
    ValidationFailed,
)
from acme.om.intake.rules import in_person
from acme.om.levers.rules import checked
from acme.om.levers.types.lever import LeverReach
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import outbox_row, versioned_row
from acme.om.projects.policies import SessionProjectsInterface
from acme.om.steps.rules import message_step
from acme.om.tenancy import TenancyManagerInterface
from acme.om.windows.types.policy import CompactionPolicy

PUBLISHED = "agent_playbooks.agent_playbook.created"
PINNED = "agent_playbooks.pin.updated"
UNPINNED = "agent_playbooks.pin.deleted"


class AgentPlaybooksOptions(Platform):
    # The most agent playbooks one session's gates are read from.
    per_session: int = Field(default=50, gt=0)
    purge_batch: int = Field(default=1000, gt=0)
    # The characters of a brief a session holds whole once it summarizes:
    # its pinned zone's. A longer one is published with a finding.
    session_bound: int = Field(default=CompactionPolicy().pinned_bound, gt=0)
    # The most pins one read answers: a tenant's kinds, each for the tenant
    # and for each of its projects.
    pins_read: int = Field(default=1000, gt=0)


class AgentPlaybooksManagerImpl(AgentPlaybooksManagerInterface):
    def __init__(
        self,
        storage: AgentPlaybookStorageInterface,
        sessions: AgentSessionsManagerInterface,
        session_rows: AgentSessionStorageInterface,
        agents: AgentsManagerInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        options: AgentPlaybooksOptions,
        reach: LeverReach,
        kinds: AgentKindCatalog,
        projects: SessionProjectsInterface,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._sessions = sessions
        self._session_rows = session_rows
        self._agents = agents
        self._tenancy = tenancy
        self._relay = relay
        self._options = options
        self._reach = reach
        self._kinds = kinds
        self._projects = projects
        self._clock = clock

    async def publish(
        self,
        ctx: TenantContext,
        draft: AgentPlaybookDraft,
        *,
        agent_playbook_id: UUID | None = None,
    ) -> AgentPlaybook:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized(
                "an agent playbook is published by a person, never by an agent's call"
            )
        latest = await self._storage.read_latest(ctx.org_id, draft.name)
        agent_playbook = AgentPlaybook(
            id=agent_playbook_id or new_id(),
            created_at=self._clock(),
            name=draft.name,
            version=1 if latest is None else latest.version + 1,
            description=draft.description,
            body=draft.body,
            gates=draft.gates,
            published_by=ctx.user_id,
        )
        # The checks read the words the person wrote, its description and
        # its steps, never the frontmatter the platform writes around them;
        # the size is the brief's as a session receives it. They advise:
        # what they find is kept with the version, and the publish stands.
        findings = checked(
            f"{agent_playbook.description}\n\n{agent_playbook.body}",
            self._reach,
            bound=self._options.session_bound,
            size=len(skill_md(agent_playbook)),
            tools=(gate.tool for gate in draft.gates if gate.tool is not None),
        )
        agent_playbook = agent_playbook.model_copy(update={"findings": findings})
        rows = (versioned_row(ctx, PUBLISHED, agent_playbook.id, agent_playbook.version),)
        try:
            landed = await self._storage.create_agent_playbook(ctx.org_id, agent_playbook, rows)
        except UniqueKeyTaken as taken:
            raise Conflict(f"agent playbook {draft.name} was published meanwhile") from taken
        if not landed:
            stored = await self._storage.read_agent_playbook(ctx.org_id, agent_playbook.id)
            if stored is None:
                raise TenantMismatch(f"agent playbook {agent_playbook.id} is not in {ctx.org_id}")
            return stored
        await self._relay.relay_all(ctx.org_id, rows)
        return agent_playbook

    async def get_agent_playbook(self, ctx: TenantContext, name: str) -> AgentPlaybook:
        ctx.require(Permission.READ)
        found = await self._storage.read_latest(ctx.org_id, name)
        if found is None:
            raise NotFound(f"agent playbook {name} not found")
        return found

    async def invoke(
        self, ctx: TenantContext, session_id: UUID, name: str
    ) -> AgentPlaybookInvocation:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized(
                "an agent playbook is invoked by a principal, never by an agent's call"
            )
        await self._agents.require_instructor(ctx, session_id)
        return await self._invoked(ctx, session_id, await self.get_agent_playbook(ctx, name))

    async def invoke_version(
        self, ctx: TenantContext, session_id: UUID, agent_playbook_id: UUID
    ) -> AgentPlaybookInvocation:
        ctx.require(Permission.WRITE)
        await self._agents.require_instructor(ctx, session_id)
        agent_playbook = await self._storage.read_agent_playbook(ctx.org_id, agent_playbook_id)
        if agent_playbook is None:
            raise NotFound(f"agent playbook {agent_playbook_id} not found")
        return await self._invoked(ctx, session_id, agent_playbook)

    async def _invoked(
        self, ctx: TenantContext, session_id: UUID, agent_playbook: AgentPlaybook
    ) -> AgentPlaybookInvocation:
        """The version brought into the session: its gates first, then its
        brief as the caller's message, which wakes the session."""
        invocation = await self._storage.create_invocation(
            ctx.org_id,
            AgentPlaybookInvocation(
                id=new_id(),
                created_at=self._clock(),
                session_id=session_id,
                agent_playbook_id=agent_playbook.id,
                name=agent_playbook.name,
                version=agent_playbook.version,
                invoked_by=ctx.user_id,
            ),
        )
        if invocation.pinned:
            # The session's kind manual: its brief is its standing text already.
            return invocation
        # The brief is the caller's word: one message an invocation, so a
        # second invocation of the version sends nothing new.
        brief = message_step(
            derived_id(invocation.id, invocation.created_at, "agent_playbook"),
            self._clock(),
            session_id,
            ctx,
            skill_md(agent_playbook),
        )
        await self._sessions.receive(ctx, session_id, [brief])
        return invocation

    async def pin(
        self, ctx: TenantContext, kind: str, name: str, project_id: UUID | None = None
    ) -> AgentPlaybookPin:
        self._may_pin(ctx)
        self._kinds.latest(kind)
        if project_id is not None and not await self._projects.holds(ctx, project_id):
            raise NotFound(f"project {project_id} not found")
        agent_playbook = await self.get_agent_playbook(ctx, name)
        # The brief rides every request of the sessions it reaches, whole:
        # one past what a session's standing text holds is refused here,
        # never at a session's start.
        size = len(skill_md(agent_playbook))
        if size > MAX_STANDING:
            raise ValidationFailed(
                f"agent playbook {name} version {agent_playbook.version} is {size} characters as a session"
                f" receives it, past the bound of {MAX_STANDING} a session's standing text holds"
            )
        now = self._clock()
        held = await self._storage.read_pin(ctx.org_id, kind, project_id)
        pin = AgentPlaybookPin(
            id=new_id() if held is None else held.id,
            created_at=now if held is None else held.created_at,
            created_by=ctx.user_id if held is None else held.created_by,
            updated_at=now,
            updated_by=ctx.user_id,
            kind=kind,
            project_id=project_id,
            agent_playbook_id=agent_playbook.id,
            name=agent_playbook.name,
            version=agent_playbook.version,
        )
        rows = (outbox_row(ctx, PINNED, pin.id, {"kind": kind, "version": agent_playbook.version}),)
        try:
            await self._storage.put_pin(ctx.org_id, pin, rows)
        except UniqueKeyTaken as taken:
            raise Conflict(f"agent kind {kind} was pinned meanwhile") from taken
        await self._relay.relay_all(ctx.org_id, rows)
        return pin

    async def unpin(
        self, ctx: TenantContext, kind: str, project_id: UUID | None = None
    ) -> AgentPlaybookPin:
        self._may_pin(ctx)
        held = await self._storage.read_pin(ctx.org_id, kind, project_id)
        if held is None:
            raise NotFound(f"agent kind {kind} has no pinned agent playbook there")
        rows = (outbox_row(ctx, UNPINNED, held.id, {"kind": kind}),)
        if not await self._storage.delete_pin(ctx.org_id, held.id, rows):
            raise NotFound(f"agent kind {kind} has no pinned agent playbook there")
        await self._relay.relay_all(ctx.org_id, rows)
        return held

    async def pins(self, ctx: TenantContext) -> tuple[AgentPlaybookPin, ...]:
        ctx.require(Permission.READ)
        return tuple(await self._storage.read_pins(ctx.org_id, self._options.pins_read))

    @staticmethod
    def _may_pin(ctx: TenantContext) -> None:
        """A pin sets what every new session of a kind holds as its standing
        text: a person's, in person, who manages the tenant's members."""
        ctx.require(Permission.MANAGE_MEMBERS)
        if not in_person(ctx):
            raise NotAuthorized("an agent playbook is pinned by a person, never by an agent's call")

    async def gates_of(self, ctx: TenantContext, session_id: UUID) -> tuple[AgentPlaybookGate, ...]:
        ctx.require(Permission.READ)
        gates: list[AgentPlaybookGate] = []
        at: UUID | None = session_id
        while at is not None:
            # The row as stored: a session marked deleted still lends its
            # gates, and the walk goes on above it.
            session = await self._session_rows.read_session(ctx.org_id, at)
            if session is None:
                raise NotFound(f"agent session {at} cannot be read, nor the gates it invoked")
            invocations = await self._storage.read_invocations(
                ctx.org_id, at, self._options.per_session
            )
            for invocation in invocations:
                agent_playbook = await self._storage.read_agent_playbook(
                    ctx.org_id, invocation.agent_playbook_id
                )
                if agent_playbook is not None:
                    gates.extend(agent_playbook.gates)
            at = session.parent_id
        return tuple(gates)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)
