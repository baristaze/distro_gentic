from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.request import Start
from acme.om.base import Platform, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import NotFound, TenantMismatch
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, outbox_row
from acme.om.projects.exceptions import ProjectFixed
from acme.om.projects.impl.sessions import bind
from acme.om.projects.manager import ProjectsManagerInterface
from acme.om.projects.storage import ProjectStorageInterface
from acme.om.projects.types.project import Project, Repository
from acme.om.tenancy import TenancyManagerInterface

CREATED = "projects.project.created"


class ProjectsOptions(Platform):
    purge_batch: int = 1000  # rows one purge statement deletes at most


class ProjectsManagerImpl(ProjectsManagerInterface):
    def __init__(
        self,
        storage: ProjectStorageInterface,
        sessions: AgentSessionsManagerInterface,
        agents: AgentsManagerInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        options: ProjectsOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._sessions = sessions
        self._agents = agents
        self._tenancy = tenancy
        self._relay = relay
        self._options = options
        self._clock = clock

    async def create_project(self, ctx: TenantContext, project: Project) -> Project:
        ctx.require(Permission.MANAGE_MEMBERS)
        now = self._clock()
        created = project.model_copy(
            update={
                "created_at": now,
                "updated_at": now,
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
            }
        )
        rows = (outbox_row(ctx, CREATED, created.id, {}),)
        if await self._storage.create_project(ctx.org_id, created, rows):
            await self._relay_all(ctx, rows)
            return created
        stored = await self._storage.read_project(ctx.org_id, created.id)
        if stored is None:
            raise TenantMismatch(f"project {created.id} is not in {ctx.org_id}")
        return stored

    async def get_project(self, ctx: TenantContext, project_id: UUID) -> Project:
        ctx.require(Permission.READ)
        return await self._project(ctx, project_id)

    async def start_session(
        self, ctx: TenantContext, project_id: UUID, start: Start
    ) -> AgentSession:
        ctx.require(Permission.WRITE)
        project = await self._project(ctx, project_id)
        if await self._storage.read_binding(ctx.org_id, start.id) is None:
            # Set when it is created: a session that stands already was
            # created under no project, and stays there.
            if await self._exists(ctx, start.id):
                raise ProjectFixed(f"agent session {start.id} was created under no project")
        await bind(self._storage, ctx.org_id, start.id, project.id, self._clock())
        return await self._agents.start_session(ctx, start)

    async def project_of(self, ctx: TenantContext, session_id: UUID) -> Project | None:
        ctx.require(Permission.READ)
        binding = await self._storage.read_binding(ctx.org_id, session_id)
        if binding is None:
            return None
        return await self._project(ctx, binding.project_id)

    async def work_repository(self, ctx: TenantContext, session_id: UUID) -> Repository | None:
        project = await self.project_of(ctx, session_id)
        return None if project is None else project.repository

    async def purge_session(self, org_id: UUID, session_id: UUID) -> bool:
        return await self._storage.purge_session(org_id, session_id)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    async def _project(self, ctx: TenantContext, project_id: UUID) -> Project:
        stored = await self._storage.read_project(ctx.org_id, project_id)
        if stored is None:
            raise NotFound(f"project {project_id} not found")
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
