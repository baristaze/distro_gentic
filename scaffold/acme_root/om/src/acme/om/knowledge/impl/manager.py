from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import Platform, new_id, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import (
    Conflict,
    NotAuthorized,
    NotFound,
    PreconditionFailed,
    TenantMismatch,
)
from acme.om.intake.rules import in_person
from acme.om.knowledge.manager import KnowledgeManagerInterface
from acme.om.knowledge.rules import ranked, reaches, recalled_step, slug_of, triggered
from acme.om.knowledge.storage import KnowledgeStorageInterface
from acme.om.knowledge.types.knowledge import Knowledge, KnowledgeStatus
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, versioned_row
from acme.om.projects.policies import SessionProjectsInterface
from acme.om.tenancy import TenancyManagerInterface

CREATED = "knowledge.entry.created"
REVIEWED = "knowledge.entry.updated"  # a review or an edit


class KnowledgeOptions(Platform):
    page: int = Field(default=200, gt=0)
    # The most entries one recall brings into a session.
    most: int = Field(default=10, gt=0)
    # The most entries one search answers.
    most_found: int = Field(default=10, gt=0)
    purge_batch: int = Field(default=1000, gt=0)


class KnowledgeManagerImpl(KnowledgeManagerInterface):
    def __init__(
        self,
        storage: KnowledgeStorageInterface,
        sessions: AgentSessionsManagerInterface,
        projects: SessionProjectsInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        options: KnowledgeOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._sessions = sessions
        self._projects = projects
        self._tenancy = tenancy
        self._relay = relay
        self._options = options
        self._clock = clock

    async def suggest(
        self, ctx: TenantContext, session_id: UUID, title: str, trigger: tuple[str, ...], text: str
    ) -> Knowledge:
        ctx.require(Permission.WRITE)
        await self._sessions.get_session(ctx, session_id)
        project_id = await self._projects.project_of(ctx, session_id)
        return await self._create(
            ctx,
            title,
            trigger,
            text,
            suggested_by=session_id,
            project_id=project_id,
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
    ) -> Knowledge:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("knowledge is written by a person, never by an agent's call")
        return await self._create(
            ctx,
            title,
            trigger,
            text,
            suggested_by=None,
            project_id=None,
            entry_id=entry_id or new_id(),
        )

    async def get_entry(self, ctx: TenantContext, entry_id: UUID) -> Knowledge:
        ctx.require(Permission.READ)
        return await self._entry(ctx, entry_id)

    async def list_entries(
        self, ctx: TenantContext, status: KnowledgeStatus, after: UUID | None, limit: int
    ) -> tuple[Knowledge, ...]:
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
    ) -> Knowledge:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("knowledge is edited by a person, never by an agent's call")
        entry = await self._entry(ctx, entry_id)
        if entry.status is KnowledgeStatus.REJECTED:
            raise Conflict(f"knowledge {entry_id} is rejected; write it again instead")
        if entry.version != version:
            raise PreconditionFailed(f"knowledge {entry_id} is at version {entry.version}")
        reviewed = entry.status is KnowledgeStatus.REVIEWED
        edited = Knowledge.model_validate(
            {
                **entry.model_dump(),
                "title": title,
                "trigger": trigger,
                "text": text,
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

    async def review(self, ctx: TenantContext, entry_id: UUID, *, keep: bool) -> Knowledge:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("knowledge is reviewed by a person, never by an agent's call")
        entry = await self._entry(ctx, entry_id)
        if entry.status is not KnowledgeStatus.SUGGESTED:
            raise Conflict(f"knowledge {entry_id} is {entry.status.value} already")
        decided = entry.model_copy(
            update={
                "status": KnowledgeStatus.REVIEWED if keep else KnowledgeStatus.REJECTED,
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
        self, ctx: TenantContext, session_id: UUID, about: str
    ) -> tuple[Knowledge, ...]:
        ctx.require(Permission.WRITE)
        project_id = await self._projects.project_of(ctx, session_id)
        found: list[Knowledge] = []
        after: UUID | None = None
        while len(found) < self._options.most:
            page = await self._storage.read_reachable(
                ctx.org_id, project_id, after, self._options.page
            )
            found.extend(triggered((e for e in page if reaches(e, project_id)), about))
            if len(page) < self._options.page:
                break
            after = page[-1].id
        found = found[: self._options.most]
        if found:
            principal = Principal(kind=PrincipalKind.SERVICE, id=ctx.user_id)
            now = self._clock()
            steps = [recalled_step(entry, session_id, principal, now) for entry in found]
            await self._sessions.receive(ctx, session_id, steps)
        return tuple(found)

    async def search(
        self, ctx: TenantContext, session_id: UUID, query: str, limit: int
    ) -> tuple[Knowledge, ...]:
        ctx.require(Permission.READ)
        await self._sessions.get_session(ctx, session_id)
        project_id = await self._projects.project_of(ctx, session_id)
        # Every entry the session reaches is read, a page at a time: a
        # tenant's reviewed knowledge is what its people kept by hand.
        reached: list[Knowledge] = []
        after: UUID | None = None
        while True:
            page = await self._storage.read_reachable(
                ctx.org_id, project_id, after, self._options.page
            )
            reached.extend(e for e in page if reaches(e, project_id))
            if len(page) < self._options.page:
                break
            after = page[-1].id
        most = max(1, min(limit, self._options.most_found))
        return tuple(ranked(reached, query, most))

    async def read(self, ctx: TenantContext, session_id: UUID, slug: str) -> Knowledge:
        ctx.require(Permission.READ)
        await self._sessions.get_session(ctx, session_id)
        project_id = await self._projects.project_of(ctx, session_id)
        entry = await self._storage.read_by_slug(ctx.org_id, project_id, slug)
        if entry is None or not reaches(entry, project_id):
            raise NotFound(f"no knowledge {slug!r} this session reaches")
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
        project_id: UUID | None,
        entry_id: UUID,
    ) -> Knowledge:
        now = self._clock()
        by_person = suggested_by is None
        entry = Knowledge(
            id=entry_id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            title=title,
            trigger=trigger,
            text=text,
            status=KnowledgeStatus.REVIEWED if by_person else KnowledgeStatus.SUGGESTED,
            suggested_by=suggested_by,
            reviewed_by=ctx.user_id if by_person else None,
            project_id=project_id,
            slug=slug_of(title, entry_id),
        )
        rows = (versioned_row(ctx, CREATED, entry.id, entry.version),)
        if not await self._storage.create_entry(ctx.org_id, entry, rows):
            stored = await self._storage.read_entry(ctx.org_id, entry.id)
            if stored is None:
                raise TenantMismatch(f"knowledge {entry.id} is not in {ctx.org_id}")
            return stored
        await self._relay_all(ctx, rows)
        return entry

    async def _entry(self, ctx: TenantContext, entry_id: UUID) -> Knowledge:
        entry = await self._storage.read_entry(ctx.org_id, entry_id)
        if entry is None:
            raise NotFound(f"knowledge {entry_id} not found")
        return entry

    async def _relay_all(self, ctx: TenantContext, rows: tuple[OutboxRow, ...]) -> None:
        await self._relay.relay_all(ctx.org_id, rows)
