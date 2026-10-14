"""The agent projects service: a tenant's agent projects, each bound to one repository,
created, read, renamed, and removed; the workspace base its sessions'
workspaces start from, set and taken away; and the fetch credential its
repository is read with, written and never read back."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.agent_projects import (
    AgentProjectView,
    AgentWorkspaceBaseBody,
    CreateAgentProjectRequest,
    FetchCredentialRequest,
    FetchCredentialView,
    RenameAgentProjectRequest,
)


class AgentProjectsServiceInterface(ABC):
    @abstractmethod
    async def create_agent_project(
        self, ctx: TenantContext, body: CreateAgentProjectRequest, agent_project_id: UUID
    ) -> AgentProjectView: ...

    @abstractmethod
    async def list_agent_projects(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> list[AgentProjectView]: ...

    @abstractmethod
    async def get_agent_project(
        self, ctx: TenantContext, agent_project_id: UUID
    ) -> AgentProjectView: ...

    @abstractmethod
    async def rename_agent_project(
        self, ctx: TenantContext, agent_project_id: UUID, body: RenameAgentProjectRequest
    ) -> AgentProjectView: ...

    @abstractmethod
    async def set_workspace_base(
        self, ctx: TenantContext, agent_project_id: UUID, body: AgentWorkspaceBaseBody | None
    ) -> AgentProjectView:
        """The agent project with the workspace base its sessions' workspaces start
        from, or with none. It reaches the sessions created after it."""
        ...

    @abstractmethod
    async def remove_agent_project(
        self, ctx: TenantContext, agent_project_id: UUID
    ) -> AgentProjectView:
        """The agent project as it stood, removed while no session belongs to it,
        and its fetch credential with it."""
        ...

    @abstractmethod
    async def put_fetch_credential(
        self, ctx: TenantContext, agent_project_id: UUID, body: FetchCredentialRequest
    ) -> FetchCredentialView: ...
