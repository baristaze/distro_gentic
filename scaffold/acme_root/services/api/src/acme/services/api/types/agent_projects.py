"""Wire types of a tenant's agent projects: one as stored, with the repository it
binds and the workspace base its sessions' workspaces start from; a new one, a
new name, and a new workspace base; and the fetch credential its repository is
read with, which is written and never read back."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, SecretStr, field_validator

from acme.om.agent_projects.types.agent_project import (
    HOST,
    IMAGE,
    MAX_AGENT_PROJECT_NAME,
    MAX_REGISTRIES,
    MAX_SETUP,
    REPOSITORY_PATH,
    SetupCommand,
)
from acme.om.agent_workspaces.types.egress import Destination
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


class AgentWorkspaceBaseBody(RequestBody):
    """The workspace base an agent project's sessions' workspaces start from: the
    image, the commands that set it up, run once in order, and the package
    registries the setup reaches. A setup that names a registry runs with
    open egress; one that names none reaches nothing. Registries serve a
    setup, so they come with one."""

    image: str = Field(min_length=1, max_length=255, pattern=IMAGE)
    setup: list[SetupCommand] = Field(default_factory=lambda: [], max_length=MAX_SETUP)
    registries: list[Destination] = Field(default_factory=lambda: [], max_length=MAX_REGISTRIES)


class AgentWorkspaceBaseView(View):
    image: str
    setup: list[str]
    registries: list[str]


class CreateAgentProjectRequest(RequestBody):
    """An agent project and the one repository it binds, which never moves; whether
    a kind that keeps its workspace by snapshots keeps it so here, False
    keeping each of its sessions' workspaces a cache; and the workspace base
    its sessions' workspaces start from, if it names one."""

    name: str = Field(min_length=1, max_length=MAX_AGENT_PROJECT_NAME)
    repository: RepositoryBody
    workspace_snapshots: bool = True
    agent_workspace_base: AgentWorkspaceBaseBody | None = None


class RenameAgentProjectRequest(RequestBody):
    name: str = Field(min_length=1, max_length=MAX_AGENT_PROJECT_NAME)


class AgentProjectView(View):
    id: UUID
    name: str
    repository: RepositoryView
    workspace_snapshots: bool
    agent_workspace_base: AgentWorkspaceBaseView | None
    created_at: datetime
    created_by: UUID
    updated_at: datetime
    updated_by: UUID


class FetchCredentialRequest(RequestBody):
    """A read-only credential of the agent project's repository, as source control
    takes it over HTTPS. It goes to the tenant's store and is never read
    back."""

    username: str = Field(min_length=1, max_length=200, pattern=r"^[^:\s]+$")
    password: SecretStr = Field(min_length=1, max_length=4096)


class FetchCredentialView(View):
    """That the agent project's repository has a fetch credential, and who gave it
    when. Never its value."""

    agent_project_id: UUID
    version: int
    updated_at: datetime
    updated_by: UUID
