from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.om.base import utcnow
from acme.om.context import TenantContext
from acme.om.projects import ProjectsManagerInterface
from acme.om.projects.types.project import Project
from acme.om.workspaces import WorkspacesManagerInterface
from acme.om.workspaces.types.credential import FetchCredential
from acme.services.api.services.impl.built import built
from acme.services.api.services.projects import ProjectsServiceInterface
from acme.services.api.types.projects import (
    CreateProjectRequest,
    FetchCredentialRequest,
    FetchCredentialView,
    ProjectView,
    RenameProjectRequest,
)


class ProjectsServiceImpl(ProjectsServiceInterface):
    def __init__(
        self,
        projects: ProjectsManagerInterface,
        workspaces: WorkspacesManagerInterface,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._projects = projects
        self._workspaces = workspaces
        self._clock = clock

    async def create_project(
        self, ctx: TenantContext, body: CreateProjectRequest, project_id: UUID
    ) -> ProjectView:
        now = self._clock()
        project = built(
            Project,
            {
                "id": project_id,
                "created_at": now,
                "updated_at": now,
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
                "name": body.name,
                "repository": body.repository.model_dump(),
            },
        )
        return ProjectView.model_validate(await self._projects.create_project(ctx, project))

    async def list_projects(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> list[ProjectView]:
        found = await self._projects.list_projects(ctx, after, limit)
        return [ProjectView.model_validate(project) for project in found]

    async def get_project(self, ctx: TenantContext, project_id: UUID) -> ProjectView:
        return ProjectView.model_validate(await self._projects.get_project(ctx, project_id))

    async def rename_project(
        self, ctx: TenantContext, project_id: UUID, body: RenameProjectRequest
    ) -> ProjectView:
        renamed = await self._projects.rename_project(ctx, project_id, body.name)
        return ProjectView.model_validate(renamed)

    async def remove_project(self, ctx: TenantContext, project_id: UUID) -> ProjectView:
        removed = await self._projects.remove_project(ctx, project_id)
        # After the project, never before: a project a session belongs to
        # stays, and keeps the credential its sessions' work is read with.
        await self._workspaces.remove_fetch_credential(ctx, project_id)
        return ProjectView.model_validate(removed)

    async def put_fetch_credential(
        self, ctx: TenantContext, project_id: UUID, body: FetchCredentialRequest
    ) -> FetchCredentialView:
        credential = built(
            FetchCredential,
            {"username": body.username, "password": body.password.get_secret_value()},
        )
        record = await self._workspaces.put_fetch_credential(ctx, project_id, credential)
        return FetchCredentialView(
            project_id=record.id,
            version=record.version,
            updated_at=record.updated_at,
            updated_by=record.updated_by,
        )
