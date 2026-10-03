"""A tenant's projects: create one bound to its repository, list and read
them, rename one, and remove one no session belongs to. And the fetch
credential the platform reads the repository with, written and never read
back. An owner's or an admin's to write; any member's to read."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.resolve import ProjectsService
from acme.services.api.types.common import LIMIT_DEFAULT
from acme.services.api.types.projects import (
    CreateProjectRequest,
    FetchCredentialRequest,
    FetchCredentialView,
    ProjectView,
    RenameProjectRequest,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectView, status_code=201)
async def create_project(
    ctx: Ctx, projects: ProjectsService, body: CreateProjectRequest, idem: Idem
) -> Response:
    """A project bound to its repository, which never moves."""
    return await idem.run(
        201, lambda attempt: projects.create_project(ctx, body, attempt.target_id)
    )


@router.get("", response_model=list[ProjectView])
async def list_projects(
    ctx: Ctx, projects: ProjectsService, after: UUID | None = None, limit: int = LIMIT_DEFAULT
) -> list[ProjectView]:
    """The tenant's projects by id, after the id `after` names."""
    return await projects.list_projects(ctx, after, limit)


@router.get("/{project_id}", response_model=ProjectView)
async def get_project(ctx: Ctx, projects: ProjectsService, project_id: UUID) -> ProjectView:
    return await projects.get_project(ctx, project_id)


@router.patch("/{project_id}", response_model=ProjectView)
async def rename_project(
    ctx: Ctx, projects: ProjectsService, project_id: UUID, body: RenameProjectRequest
) -> ProjectView:
    return await projects.rename_project(ctx, project_id, body)


@router.delete("/{project_id}", response_model=ProjectView)
async def remove_project(ctx: Ctx, projects: ProjectsService, project_id: UUID) -> ProjectView:
    """The project as it stood, with its fetch credential gone. 409
    `project_in_use` while a session belongs to it."""
    return await projects.remove_project(ctx, project_id)


@router.put("/{project_id}/credential", response_model=FetchCredentialView)
async def put_fetch_credential(
    ctx: Ctx, projects: ProjectsService, project_id: UUID, body: FetchCredentialRequest
) -> FetchCredentialView:
    """A read-only credential of the project's repository; a later one
    replaces it. The answer says who gave it when, never its value."""
    return await projects.put_fetch_credential(ctx, project_id, body)
