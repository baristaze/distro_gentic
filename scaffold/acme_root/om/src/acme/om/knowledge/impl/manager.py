from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import Platform, new_id, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import Conflict, NotAuthorized, NotFound
from acme.om.intake.rules import in_person
from acme.om.knowledge.manager import KnowledgeManagerInterface
from acme.om.knowledge.rules import recalled_step, triggered
from acme.om.knowledge.storage import KnowledgeStorageInterface
from acme.om.knowledge.types.knowledge import Knowledge, KnowledgeStatus
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, versioned_row
from acme.om.tenancy import TenancyManagerInterface

CREATED = "knowledge.entry.created"
REVIEWED = "knowledge.entry.updated"


class KnowledgeOptions(Platform):
    page: int = Field(default=200, gt=0)
    # The most entries one recall brings into a session.
    most: int = Field(default=10, gt=0)
    purge_batch: int = Field(default=1000, gt=0)


class KnowledgeManagerImpl(KnowledgeManagerInterface):
    def __init__(
        self,
        storage: KnowledgeStorageInterface,
        sessions: AgentSessionsManagerInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        options: KnowledgeOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._sessions = sessions
        self._tenancy = tenancy
        self._relay = relay
        self._options = options
        self._clock = clock

    async def suggest(
        self, ctx: TenantContext, session_id: UUID, title: str, trigger: tuple[str, ...], text: str
    ) -> Knowledge:
        ctx.require(Permission.WRITE)
        await self._sessions.get_session(ctx, session_id)
        return await self._create(ctx, title, trigger, text, suggested_by=session_id)

    async def write(
        self, ctx: TenantContext, title: str, trigger: tuple[str, ...], text: str
    ) -> Knowledge:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("knowledge is written by a person, never by an agent's call")
        return await self._create(ctx, title, trigger, text, suggested_by=None)

    async def review(self, ctx: TenantContext, entry_id: UUID, *, keep: bool) -> Knowledge:
        ctx.require(Permission.WRITE)
        if not in_person(ctx):
            raise NotAuthorized("knowledge is reviewed by a person, never by an agent's call")
        entry = await self._storage.read_entry(ctx.org_id, entry_id)
        if entry is None:
            raise NotFound(f"knowledge {entry_id} not found")
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
        found: list[Knowledge] = []
        after: UUID | None = None
        while len(found) < self._options.most:
            page = await self._storage.read_entries(
                ctx.org_id, KnowledgeStatus.REVIEWED, after, self._options.page
            )
            found.extend(triggered(page, about))
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
    ) -> Knowledge:
        now = self._clock()
        by_person = suggested_by is None
        entry = Knowledge(
            id=new_id(),
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
        )
        rows = (versioned_row(ctx, CREATED, entry.id, entry.version),)
        await self._storage.create_entry(ctx.org_id, entry, rows)
        await self._relay_all(ctx, rows)
        return entry

    async def _relay_all(self, ctx: TenantContext, rows: tuple[OutboxRow, ...]) -> None:
        await self._relay.relay_all(ctx.org_id, rows)
