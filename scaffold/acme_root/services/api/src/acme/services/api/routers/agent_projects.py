"""A tenant's agent projects: create one bound to its repository, list and read
them, rename one, set or take away the workspace base its sessions'
workspaces start from, and remove one no session belongs to. And the fetch
credential the platform reads the repository with, written and never read
back. An owner's or an admin's to write; any member's to read."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.resolve import AgentProjectsService
from acme.services.api.types.agent_projects import (
    AgentProjectView,
    AgentWorkspaceBaseBody,
    CreateAgentProjectRequest,
    FetchCredentialRequest,
    FetchCredentialView,
    RenameAgentProjectRequest,
)
from acme.services.api.types.common import LIMIT_DEFAULT

router = APIRouter(prefix="/agent-projects", tags=["agent_projects"])


@router.post("", response_model=AgentProjectView, status_code=201)
async def create_agent_project(
    ctx: Ctx, agent_projects: AgentProjectsService, body: CreateAgentProjectRequest, idem: Idem
) -> Response:
    """An agent project bound to its repository, which never moves."""
    return await idem.run(
        201, lambda attempt: agent_projects.create_agent_project(ctx, body, attempt.target_id)
    )


@router.get("", response_model=list[AgentProjectView])
async def list_agent_projects(
    ctx: Ctx,
    agent_projects: AgentProjectsService,
    after: UUID | None = None,
    limit: int = LIMIT_DEFAULT,
) -> list[AgentProjectView]:
    """The tenant's agent projects by id, after the id `after` names."""
    return await agent_projects.list_agent_projects(ctx, after, limit)


@router.get("/{agent_project_id}", response_model=AgentProjectView)
async def get_agent_project(
    ctx: Ctx, agent_projects: AgentProjectsService, agent_project_id: UUID
) -> AgentProjectView:
    return await agent_projects.get_agent_project(ctx, agent_project_id)


@router.patch("/{agent_project_id}", response_model=AgentProjectView)
async def rename_agent_project(
    ctx: Ctx,
    agent_projects: AgentProjectsService,
    agent_project_id: UUID,
    body: RenameAgentProjectRequest,
) -> AgentProjectView:
    return await agent_projects.rename_agent_project(ctx, agent_project_id, body)


@router.put("/{agent_project_id}/workspace-base", response_model=AgentProjectView)
async def set_workspace_base(
    ctx: Ctx,
    agent_projects: AgentProjectsService,
    agent_project_id: UUID,
    body: AgentWorkspaceBaseBody,
) -> AgentProjectView:
    """The workspace base the agent project's sessions' workspaces start from; a later
    one replaces it. Each session keeps the one it started on, and a changed
    one is built again for the sessions created after it."""
    return await agent_projects.set_workspace_base(ctx, agent_project_id, body)


@router.delete("/{agent_project_id}/workspace-base", response_model=AgentProjectView)
async def remove_workspace_base(
    ctx: Ctx, agent_projects: AgentProjectsService, agent_project_id: UUID
) -> AgentProjectView:
    """The agent project with no workspace base: its sessions created after it start
    from their kind's own workspace."""
    return await agent_projects.set_workspace_base(ctx, agent_project_id, None)


@router.delete("/{agent_project_id}", response_model=AgentProjectView)
async def remove_agent_project(
    ctx: Ctx, agent_projects: AgentProjectsService, agent_project_id: UUID
) -> AgentProjectView:
    """The agent project as it stood, with its fetch credential gone. 409
    `agent_project_in_use` while a session belongs to it."""
    return await agent_projects.remove_agent_project(ctx, agent_project_id)


@router.put("/{agent_project_id}/credential", response_model=FetchCredentialView)
async def put_fetch_credential(
    ctx: Ctx,
    agent_projects: AgentProjectsService,
    agent_project_id: UUID,
    body: FetchCredentialRequest,
) -> FetchCredentialView:
    """A read-only credential of the agent project's repository; a later one
    replaces it. The answer says who gave it when, never its value."""
    return await agent_projects.put_fetch_credential(ctx, agent_project_id, body)
