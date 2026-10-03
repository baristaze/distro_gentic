from uuid import UUID

from acme.om.context import TenantContext
from acme.om.projects.policies import SessionProjectsInterface
from acme.om.projects.storage import ProjectStorageInterface


class SessionProjectsBoundImpl(SessionProjectsInterface):
    """The projects' answers, from their rows: the one the projects' start,
    or the session's origin, wrote before the session, and the tenant's
    projects. A session with no row belongs to no project."""

    def __init__(self, storage: ProjectStorageInterface) -> None:
        self._storage = storage

    async def project_of(self, ctx: TenantContext, session_id: UUID) -> UUID | None:
        binding = await self._storage.read_binding(ctx.org_id, session_id)
        return None if binding is None else binding.project_id

    async def holds(self, ctx: TenantContext, project_id: UUID) -> bool:
        return await self._storage.read_project(ctx.org_id, project_id) is not None
