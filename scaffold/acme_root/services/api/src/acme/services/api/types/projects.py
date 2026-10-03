"""Wire types of a tenant's projects: one as stored, with the repository it
binds; a new one, and a new name; and the fetch credential its repository is
read with, which is written and never read back."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, SecretStr, field_validator

from acme.om.projects.types.project import HOST, MAX_PROJECT_NAME, REPOSITORY_PATH
from acme.services.api.types.common import RequestBody, View


class RepositoryBody(RequestBody):
    """A repository by its host's domain and its path there, such as
    `github.com` and `octo/reports`. Both are compared without case."""

    host: str = Field(max_length=253, pattern=HOST)
    path: str = Field(max_length=255, pattern=REPOSITORY_PATH)

    @field_validator("host", "path", mode="before")
    @classmethod
    def _lower(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value


class RepositoryView(View):
    host: str
    path: str


class CreateProjectRequest(RequestBody):
    """A project and the one repository it binds, which never moves."""

    name: str = Field(min_length=1, max_length=MAX_PROJECT_NAME)
    repository: RepositoryBody


class RenameProjectRequest(RequestBody):
    name: str = Field(min_length=1, max_length=MAX_PROJECT_NAME)


class ProjectView(View):
    id: UUID
    name: str
    repository: RepositoryView
    created_at: datetime
    created_by: UUID
    updated_at: datetime
    updated_by: UUID


class FetchCredentialRequest(RequestBody):
    """A read-only credential of the project's repository, as source control
    takes it over HTTPS. It goes to the tenant's store and is never read
    back."""

    username: str = Field(min_length=1, max_length=200, pattern=r"^[^:\s]+$")
    password: SecretStr = Field(min_length=1, max_length=4096)


class FetchCredentialView(View):
    """That the project's repository has a fetch credential, and who gave it
    when. Never its value."""

    project_id: UUID
    version: int
    updated_at: datetime
    updated_by: UUID
