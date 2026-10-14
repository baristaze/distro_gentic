"""An agent project: a tenant's unit of work, bound to one repository. The
policies the platform keys by agent project (what validates a change, where a
workspace may reach, which secrets a command sees, retention's narrowing,
the workspace base its sessions' workspaces start from) are read through the
agent project a session belongs to, and the session's own branch and pull
request are work product on this repository alone.

An agent project's name may change. Its repository never moves, so the work
product of every session already in it stays where it was."""

from typing import Annotated, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from acme.infra.workspaces import EgressMode, EgressPolicy, WorkspaceBase
from acme.om.agent_workspaces.types.egress import Destination
from acme.om.base import Identifiable, Platform, Trackable
from acme.om.steps.types.content import Stored

MAX_AGENT_PROJECT_NAME = 200

HOST = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
"""A source-control host by its domain name, such as `github.com`."""

REPOSITORY_PATH = r"^[a-z0-9_][a-z0-9_.-]*(/[a-z0-9_][a-z0-9_.-]*)+$"
"""A repository's path on its host: an owner, any groups, and a name, such
as `octo/reports`. No segment starts with a dot, so none is `.` or `..`."""


class Repository(Platform):
    """A repository on a source-control host. Hosts compare names without
    case, so both parts are kept in lower case, and two spellings of one
    repository are one value."""

    host: str = Field(max_length=253, pattern=HOST)
    path: str = Field(max_length=255, pattern=REPOSITORY_PATH)

    @field_validator("host", "path", mode="before")
    @classmethod
    def _lower(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value


IMAGE = r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$"
"""An image by its reference, as a registry serves it: a repository, and a
tag or a digest. It starts with a letter or a digit, so the runtime never
reads it as an option."""

SetupCommand = Annotated[str, StringConstraints(min_length=1, max_length=4000)]

MAX_SETUP = 50
"""The most setup commands one workspace base runs."""

MAX_REGISTRIES = 20


class AgentWorkspaceBase(Platform):
    """What an agent project's sessions work in: the image their workspace starts
    on, and the commands that set it up, run once, in order, then kept as
    the base every workspace of a kind that takes it starts from.
    `registries` are the package registries its setup reaches, the
    agent project's choice, recorded: a setup that names one runs with open
    egress, since a setup's egress is open or none, and one that names none
    reaches nothing. A workspace on it keeps its own kind's egress."""

    image: str = Field(min_length=1, max_length=255, pattern=IMAGE)
    setup: tuple[SetupCommand, ...] = Field(default=(), max_length=MAX_SETUP)
    registries: tuple[Destination, ...] = Field(default=(), max_length=MAX_REGISTRIES)

    @model_validator(mode="after")
    def _registries_serve_a_setup(self) -> Self:
        if self.registries and not self.setup:
            raise ValueError("a workspace base names registries only for a setup to reach")
        if len(set(self.registries)) != len(self.registries):
            raise ValueError("a workspace base names each registry once")
        return self

    def base(self) -> WorkspaceBase:
        """The engine's base: the image, its setup, and the setup's egress."""
        egress = EgressMode.OPEN if self.registries else EgressMode.NONE
        return WorkspaceBase(image=self.image, setup=self.setup, egress=EgressPolicy(mode=egress))


class AgentProject(Identifiable, Trackable):
    """A tenant's agent project: its name, the one repository it binds, whether a
    kind that keeps its workspace by snapshots keeps it so here, and the
    workspace base its sessions' workspaces start from. False narrows each of
    its sessions' workspaces to a cache, on purpose. Both reach the
    sessions created after they are set; a session keeps what it pinned."""

    name: Stored = Field(min_length=1, max_length=MAX_AGENT_PROJECT_NAME)
    repository: Repository
    workspace_snapshots: bool = True
    workspace_base: AgentWorkspaceBase | None = None
