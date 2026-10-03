"""The projects service: a tenant's projects, each bound to one repository,
created, read, renamed, and removed, and the fetch credential its repository
is read with, written and never read back."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.projects import (
    CreateProjectRequest,
    FetchCredentialRequest,
    FetchCredentialView,
    ProjectView,
    RenameProjectRequest,
)


class ProjectsServiceInterface(ABC):
    @abstractmethod
    async def create_project(
        self, ctx: TenantContext, body: CreateProjectRequest, project_id: UUID
    ) -> ProjectView: ...

    @abstractmethod
    async def list_projects(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> list[ProjectView]: ...

    @abstractmethod
    async def get_project(self, ctx: TenantContext, project_id: UUID) -> ProjectView: ...

    @abstractmethod
    async def rename_project(
        self, ctx: TenantContext, project_id: UUID, body: RenameProjectRequest
    ) -> ProjectView: ...

    @abstractmethod
    async def remove_project(self, ctx: TenantContext, project_id: UUID) -> ProjectView:
        """The project as it stood, removed while no session belongs to it,
        and its fetch credential with it."""
        ...

    @abstractmethod
    async def put_fetch_credential(
        self, ctx: TenantContext, project_id: UUID, body: FetchCredentialRequest
    ) -> FetchCredentialView: ...
