from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.om.agent_projects.exceptions import AgentProjectFixed, AgentProjectInUse
from acme.om.agent_projects.impl.sessions import bind
from acme.om.agent_projects.manager import AgentProjectsManagerInterface
from acme.om.agent_projects.storage import AgentProjectStorageInterface
from acme.om.agent_projects.types.agent_project import AgentProject, AgentWorkspaceBase, Repository
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.request import Start
from acme.om.base import Platform, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import NotFound, TenantMismatch
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, outbox_row
from acme.om.tenancy import TenancyManagerInterface

CREATED = "agent_projects.agent_project.created"
UPDATED = "agent_projects.agent_project.updated"
DELETED = "agent_projects.agent_project.deleted"


class AgentProjectsOptions(Platform):
    purge_batch: int = 1000  # rows one purge statement deletes at most
    page: int = 200  # the most agent projects one list answers


class AgentProjectsManagerImpl(AgentProjectsManagerInterface):
    def __init__(
        self,
        storage: AgentProjectStorageInterface,
        sessions: AgentSessionsManagerInterface,
        agents: AgentsManagerInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        options: AgentProjectsOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._sessions = sessions
        self._agents = agents
        self._tenancy = tenancy
        self._relay = relay
        self._options = options
        self._clock = clock

    async def create_agent_project(
        self, ctx: TenantContext, agent_project: AgentProject
    ) -> AgentProject:
        ctx.require(Permission.MANAGE_MEMBERS)
        now = self._clock()
        created = agent_project.model_copy(
            update={
                "created_at": now,
                "updated_at": now,
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
            }
        )
        rows = (outbox_row(ctx, CREATED, created.id, {}),)
        if await self._storage.create_agent_project(ctx.org_id, created, rows):
            await self._relay_all(ctx, rows)
            return created
        stored = await self._storage.read_agent_project(ctx.org_id, created.id)
        if stored is None:
            raise TenantMismatch(f"agent project {created.id} is not in {ctx.org_id}")
        return stored

    async def get_agent_project(self, ctx: TenantContext, agent_project_id: UUID) -> AgentProject:
        ctx.require(Permission.READ)
        return await self._agent_project(ctx, agent_project_id)

    async def list_agent_projects(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> tuple[AgentProject, ...]:
        ctx.require(Permission.READ)
        limit = max(1, min(limit, self._options.page))
        return tuple(await self._storage.read_agent_projects(ctx.org_id, after, limit))

    async def rename_agent_project(
        self, ctx: TenantContext, agent_project_id: UUID, name: str
    ) -> AgentProject:
        ctx.require(Permission.MANAGE_MEMBERS)
        return await self._update(ctx, agent_project_id, {"name": name})

    async def set_workspace_base(
        self, ctx: TenantContext, agent_project_id: UUID, workspace_base: AgentWorkspaceBase | None
    ) -> AgentProject:
        ctx.require(Permission.MANAGE_MEMBERS)
        return await self._update(ctx, agent_project_id, {"workspace_base": workspace_base})

    async def remove_agent_project(
        self, ctx: TenantContext, agent_project_id: UUID
    ) -> AgentProject:
        ctx.require(Permission.MANAGE_MEMBERS)
        stored = await self._agent_project(ctx, agent_project_id)
        rows = (outbox_row(ctx, DELETED, stored.id, {}),)
        if not await self._storage.delete_agent_project(ctx.org_id, agent_project_id, rows):
            if await self._storage.read_agent_project(ctx.org_id, agent_project_id) is None:
                raise NotFound(f"agent project {agent_project_id} not found")
            raise AgentProjectInUse(f"agent project {agent_project_id} has sessions, and stays")
        await self._relay_all(ctx, rows)
        return stored

    async def start_session(
        self, ctx: TenantContext, agent_project_id: UUID, start: Start
    ) -> AgentSession:
        ctx.require(Permission.WRITE)
        agent_project = await self._agent_project(ctx, agent_project_id)
        if await self._storage.read_binding(ctx.org_id, start.id) is None:
            # Set when it is created: a session that stands already was
            # created under no agent project, and stays there.
            if await self._exists(ctx, start.id):
                raise AgentProjectFixed(
                    f"agent session {start.id} was created under no agent project"
                )
        await bind(self._storage, ctx.org_id, start.id, agent_project.id, self._clock())
        return await self._agents.start_session(ctx, start)

    async def agent_project_of(self, ctx: TenantContext, session_id: UUID) -> AgentProject | None:
        ctx.require(Permission.READ)
        binding = await self._storage.read_binding(ctx.org_id, session_id)
        if binding is None:
            return None
        return await self._agent_project(ctx, binding.agent_project_id)

    async def work_repository(self, ctx: TenantContext, session_id: UUID) -> Repository | None:
        agent_project = await self.agent_project_of(ctx, session_id)
        return None if agent_project is None else agent_project.repository

    async def purge_session(self, org_id: UUID, session_id: UUID) -> bool:
        return await self._storage.purge_session(org_id, session_id)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    async def _update(
        self, ctx: TenantContext, agent_project_id: UUID, update: dict[str, object]
    ) -> AgentProject:
        """The stored agent project with `update` written over it, announced."""
        stored = await self._agent_project(ctx, agent_project_id)
        updated = AgentProject.model_validate(
            {
                **stored.model_dump(),
                **update,
                "updated_at": self._clock(),
                "updated_by": ctx.user_id,
            }
        )
        rows = (outbox_row(ctx, UPDATED, updated.id, {}),)
        if not await self._storage.write_agent_project(ctx.org_id, updated, rows):
            raise NotFound(f"agent project {agent_project_id} not found")
        await self._relay_all(ctx, rows)
        return updated

    async def _agent_project(self, ctx: TenantContext, agent_project_id: UUID) -> AgentProject:
        stored = await self._storage.read_agent_project(ctx.org_id, agent_project_id)
        if stored is None:
            raise NotFound(f"agent project {agent_project_id} not found")
        return stored

    async def _exists(self, ctx: TenantContext, session_id: UUID) -> bool:
        try:
            await self._sessions.get_session(ctx, session_id)
        except NotFound:
            return False
        return True

    async def _relay_all(self, ctx: TenantContext, rows: tuple[OutboxRow, ...]) -> None:
        """The write has committed; a relay that fails is left to the sweep."""
        await self._relay.relay_all(ctx.org_id, rows)
