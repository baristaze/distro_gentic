from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.agent_knowledge.manager import AgentKnowledgeManagerInterface
from acme.om.agent_knowledge.rules import ranked, reaches, recalled_step, slug_of, triggered
from acme.om.agent_knowledge.storage import AgentKnowledgeStorageInterface
from acme.om.agent_knowledge.types.agent_knowledge import (
    AgentKnowledge,
    AgentKnowledgeRecall,
    AgentKnowledgeStatus,
)
from acme.om.agent_projects.policies import SessionAgentProjectsInterface
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import OmBase, derived_id, new_id, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import (
    Conflict,
    NotAuthorized,
    NotFound,
    PreconditionFailed,
    TenantMismatch,
)
from acme.om.intake.rules import in_person
from acme.om.levers.rules import checked
from acme.om.levers.types.lever import LeverFinding, LeverReach
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, versioned_row
from acme.om.tenancy import TenancyManagerInterface

CREATED = "agent_knowledge.entry.created"
REVIEWED = "agent_knowledge.entry.updated"  # a review or an edit


class AgentKnowledgeOptions(OmBase):
    page: int = Field(default=200, gt=0)
    # The most entries one recall brings into a session.
    most: int = Field(default=10, gt=0)
    # The most entries one search answers.
    most_found: int = Field(default=10, gt=0)
    purge_batch: int = Field(default=1000, gt=0)


class AgentKnowledgeManagerImpl(AgentKnowledgeManagerInterface):
    def __init__(
        self,
        storage: AgentKnowledgeStorageInterface,
        sessions: AgentSessionsManagerInterface,
        agent_projects: SessionAgentProjectsInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        options: AgentKnowledgeOptions,
        reach: LeverReach,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._sessions = sessions
        self._agent_projects = agent_projects
        self._tenancy = tenancy
        self._relay = relay
        self._options = options
        self._reach = reach
        self._clock = clock

    async def suggest(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        title: str,
        trigger: tuple[str, ...],
        text: str,
    ) -> AgentKnowledge:
        ctx.require(Permission.WRITE)
        await self._sessions.get_agent_session(ctx, agent_session_id)
        agent_project_id = await self._agent_projects.agent_project_of(ctx, agent_session_id)
        return await self._create(
            ctx,
            title,
            trigger,
            text,
            suggested_by=agent_session_id,
            agent_project_id=agent_project_id,
            entry_id=new_id(),
        )

    async def write(
        self,
        ctx: TenantContext,
        title: str,
        trigger: tuple[str, ...],
        text: str,
        *,
        entry_id: UUID | None = None,
    ) -> AgentKnowledge:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("agent knowledge is written by a person, never by an agent's call")
        return await self._create(
            ctx,
            title,
            trigger,
            text,
            suggested_by=None,
            agent_project_id=None,
            entry_id=entry_id or new_id(),
        )

    async def get_entry(self, ctx: TenantContext, entry_id: UUID) -> AgentKnowledge:
        ctx.require(Permission.READ)
        return await self._entry(ctx, entry_id)

    async def list_entries(
        self, ctx: TenantContext, status: AgentKnowledgeStatus, after: UUID | None, limit: int
    ) -> tuple[AgentKnowledge, ...]:
        ctx.require(Permission.READ)
        limit = max(1, min(limit, self._options.page))
        return tuple(await self._storage.read_entries(ctx.org_id, status, after, limit))

    async def edit(
        self,
        ctx: TenantContext,
        entry_id: UUID,
        title: str,
        trigger: tuple[str, ...],
        text: str,
        version: int,
    ) -> AgentKnowledge:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("agent knowledge is edited by a person, never by an agent's call")
        entry = await self._entry(ctx, entry_id)
        if entry.status is AgentKnowledgeStatus.REJECTED:
            raise Conflict(f"agent knowledge {entry_id} is rejected; write it again instead")
        if entry.version != version:
            raise PreconditionFailed(f"agent knowledge {entry_id} is at version {entry.version}")
        reviewed = entry.status is AgentKnowledgeStatus.REVIEWED
        edited = AgentKnowledge.model_validate(
            {
                **entry.model_dump(),
                "title": title,
                "trigger": trigger,
                "text": text,
                "findings": self._findings(title, text),
                "reviewed_by": ctx.user_id if reviewed else entry.reviewed_by,
                "updated_at": self._clock(),
                "updated_by": ctx.user_id,
                "version": entry.version + 1,
            }
        )
        rows = (versioned_row(ctx, REVIEWED, edited.id, edited.version),)
        await self._storage.update_entry(ctx.org_id, edited, rows)
        await self._relay_all(ctx, rows)
        return edited

    async def review(self, ctx: TenantContext, entry_id: UUID, *, keep: bool) -> AgentKnowledge:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("agent knowledge is reviewed by a person, never by an agent's call")
        entry = await self._entry(ctx, entry_id)
        if entry.status is not AgentKnowledgeStatus.SUGGESTED:
            raise Conflict(f"agent knowledge {entry_id} is {entry.status.value} already")
        decided = entry.model_copy(
            update={
                "status": AgentKnowledgeStatus.REVIEWED if keep else AgentKnowledgeStatus.REJECTED,
                # Read again against the kinds it reaches as it is kept.
                "findings": self._findings(entry.title, entry.text) if keep else entry.findings,
                "reviewed_by": ctx.user_id,
                "updated_at": self._clock(),
                "updated_by": ctx.user_id,
                "version": entry.version + 1,
            }
        )
        rows = (versioned_row(ctx, REVIEWED, decided.id, decided.version),)
        await self._storage.update_entry(ctx.org_id, decided, rows)
        await self._relay_all(ctx, rows)
        return decided

    async def recall(
        self, ctx: TenantContext, agent_session_id: UUID, about: str
    ) -> tuple[AgentKnowledge, ...]:
        ctx.require(Permission.WRITE)
        agent_project_id = await self._agent_projects.agent_project_of(ctx, agent_session_id)
        found: list[AgentKnowledge] = []
        after: UUID | None = None
        while len(found) < self._options.most:
            page = await self._storage.read_reachable(
                ctx.org_id, agent_project_id, after, self._options.page
            )
            found.extend(triggered((e for e in page if reaches(e, agent_project_id)), about))
            if len(page) < self._options.page:
                break
            after = page[-1].id
        found = found[: self._options.most]
        if found:
            principal = Principal(kind=PrincipalKind.SERVICE, id=ctx.user_id)
            now = self._clock()
            # Which version each recall brought in, kept before the session
            # reads it, so a reading of the sessions that stalled names it.
            await self._storage.create_recalls(
                ctx.org_id, tuple(self._recall(entry, agent_session_id) for entry in found)
            )
            steps = [recalled_step(entry, agent_session_id, principal, now) for entry in found]
            await self._sessions.receive(ctx, agent_session_id, steps)
        return tuple(found)

    async def search(
        self, ctx: TenantContext, agent_session_id: UUID, query: str, limit: int
    ) -> tuple[AgentKnowledge, ...]:
        ctx.require(Permission.READ)
        await self._sessions.get_agent_session(ctx, agent_session_id)
        agent_project_id = await self._agent_projects.agent_project_of(ctx, agent_session_id)
        # Every entry the session reaches is read, a page at a time: a
        # tenant's reviewed agent knowledge is what its people kept by hand.
        reached: list[AgentKnowledge] = []
        after: UUID | None = None
        while True:
            page = await self._storage.read_reachable(
                ctx.org_id, agent_project_id, after, self._options.page
            )
            reached.extend(e for e in page if reaches(e, agent_project_id))
            if len(page) < self._options.page:
                break
            after = page[-1].id
        most = max(1, min(limit, self._options.most_found))
        return tuple(ranked(reached, query, most))

    async def read(self, ctx: TenantContext, agent_session_id: UUID, slug: str) -> AgentKnowledge:
        ctx.require(Permission.READ)
        await self._sessions.get_agent_session(ctx, agent_session_id)
        agent_project_id = await self._agent_projects.agent_project_of(ctx, agent_session_id)
        entry = await self._storage.read_by_slug(ctx.org_id, agent_project_id, slug)
        if entry is None or not reaches(entry, agent_project_id):
            raise NotFound(f"no agent knowledge {slug!r} this session reaches")
        # An entry read on demand is reached as a recalled one is: its
        # version is kept for the reading of the sessions that stalled.
        await self._storage.create_recalls(ctx.org_id, (self._recall(entry, agent_session_id),))
        return entry

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    async def _create(
        self,
        ctx: TenantContext,
        title: str,
        trigger: tuple[str, ...],
        text: str,
        *,
        suggested_by: UUID | None,
        agent_project_id: UUID | None,
        entry_id: UUID,
    ) -> AgentKnowledge:
        now = self._clock()
        by_person = suggested_by is None
        entry = AgentKnowledge(
            id=entry_id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            title=title,
            trigger=trigger,
            text=text,
            status=AgentKnowledgeStatus.REVIEWED if by_person else AgentKnowledgeStatus.SUGGESTED,
            suggested_by=suggested_by,
            reviewed_by=ctx.user_id if by_person else None,
            agent_project_id=agent_project_id,
            slug=slug_of(title, entry_id),
            findings=self._findings(title, text),
        )
        rows = (versioned_row(ctx, CREATED, entry.id, entry.version),)
        if not await self._storage.create_entry(ctx.org_id, entry, rows):
            stored = await self._storage.read_entry(ctx.org_id, entry.id)
            if stored is None:
                raise TenantMismatch(f"agent knowledge {entry.id} is not in {ctx.org_id}")
            return stored
        await self._relay_all(ctx, rows)
        return entry

    def _findings(self, title: str, text: str) -> tuple[LeverFinding, ...]:
        """What the lever checks read in an entry's words, against the kinds
        its sessions start on. A recalled entry is read before any summary
        and read again on demand, so it has no bound of a session's to meet."""
        return checked(f"{title}\n{text}", self._reach)

    def _recall(self, entry: AgentKnowledge, agent_session_id: UUID) -> AgentKnowledgeRecall:
        """The record that a session reached an entry's version. Its id is
        the entry's in the session, so a recall or a read again writes
        none."""
        return AgentKnowledgeRecall(
            id=derived_id(entry.id, entry.created_at, f"recalled:{agent_session_id}"),
            created_at=self._clock(),
            agent_session_id=agent_session_id,
            entry_id=entry.id,
            version=entry.version,
        )

    async def _entry(self, ctx: TenantContext, entry_id: UUID) -> AgentKnowledge:
        entry = await self._storage.read_entry(ctx.org_id, entry_id)
        if entry is None:
            raise NotFound(f"agent knowledge {entry_id} not found")
        return entry

    async def _relay_all(self, ctx: TenantContext, rows: tuple[OutboxRow, ...]) -> None:
        await self._relay.relay_all(ctx.org_id, rows)
