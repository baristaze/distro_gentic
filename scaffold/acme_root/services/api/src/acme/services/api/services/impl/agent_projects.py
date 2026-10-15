from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.om.agent_projects import AgentProjectsManagerInterface
from acme.om.agent_projects.types.agent_project import AgentProject, AgentProjectWorkspaceBase
from acme.om.agent_workspaces import AgentWorkspacesManagerInterface
from acme.om.agent_workspaces.types.credential import FetchCredential
from acme.om.base import utcnow
from acme.om.context import TenantContext
from acme.services.api.services.agent_projects import AgentProjectsServiceInterface
from acme.services.api.services.impl.built import built
from acme.services.api.types.agent_projects import (
    AgentProjectView,
    AgentWorkspaceBaseBody,
    CreateAgentProjectRequest,
    FetchCredentialRequest,
    FetchCredentialView,
    RenameAgentProjectRequest,
)


class AgentProjectsServiceImpl(AgentProjectsServiceInterface):
    def __init__(
        self,
        agent_projects: AgentProjectsManagerInterface,
        agent_workspaces: AgentWorkspacesManagerInterface,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._agent_projects = agent_projects
        self._agent_workspaces = agent_workspaces
        self._clock = clock

    async def create_agent_project(
        self, ctx: TenantContext, body: CreateAgentProjectRequest, agent_project_id: UUID
    ) -> AgentProjectView:
        now = self._clock()
        agent_project = built(
            AgentProject,
            {
                "id": agent_project_id,
                "created_at": now,
                "updated_at": now,
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
                "name": body.name,
                "repository": body.repository.model_dump(),
                "workspace_snapshots": body.workspace_snapshots,
                "agent_workspace_base": None
                if body.agent_workspace_base is None
                else body.agent_workspace_base.model_dump(),
            },
        )
        return AgentProjectView.model_validate(
            await self._agent_projects.create_agent_project(ctx, agent_project)
        )

    async def list_agent_projects(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> list[AgentProjectView]:
        found = await self._agent_projects.list_agent_projects(ctx, after, limit)
        return [AgentProjectView.model_validate(agent_project) for agent_project in found]

    async def get_agent_project(
        self, ctx: TenantContext, agent_project_id: UUID
    ) -> AgentProjectView:
        return AgentProjectView.model_validate(
            await self._agent_projects.get_agent_project(ctx, agent_project_id)
        )

    async def rename_agent_project(
        self, ctx: TenantContext, agent_project_id: UUID, body: RenameAgentProjectRequest
    ) -> AgentProjectView:
        renamed = await self._agent_projects.rename_agent_project(ctx, agent_project_id, body.name)
        return AgentProjectView.model_validate(renamed)

    async def set_workspace_base(
        self, ctx: TenantContext, agent_project_id: UUID, body: AgentWorkspaceBaseBody | None
    ) -> AgentProjectView:
        agent_workspace_base = (
            None if body is None else built(AgentProjectWorkspaceBase, body.model_dump())
        )
        updated = await self._agent_projects.set_workspace_base(
            ctx, agent_project_id, agent_workspace_base
        )
        return AgentProjectView.model_validate(updated)

    async def remove_agent_project(
        self, ctx: TenantContext, agent_project_id: UUID
    ) -> AgentProjectView:
        removed = await self._agent_projects.remove_agent_project(ctx, agent_project_id)
        # After the agent project, never before: an agent project a session belongs to
        # stays, and keeps the credential its sessions' work is read with.
        await self._agent_workspaces.remove_fetch_credential(ctx, agent_project_id)
        return AgentProjectView.model_validate(removed)

    async def put_fetch_credential(
        self, ctx: TenantContext, agent_project_id: UUID, body: FetchCredentialRequest
    ) -> FetchCredentialView:
        credential = built(
            FetchCredential,
            {"username": body.username, "password": body.password.get_secret_value()},
        )
        record = await self._agent_workspaces.put_fetch_credential(
            ctx, agent_project_id, credential
        )
        return FetchCredentialView(
            agent_project_id=record.id,
            version=record.version,
            updated_at=record.updated_at,
            updated_by=record.updated_by,
        )
