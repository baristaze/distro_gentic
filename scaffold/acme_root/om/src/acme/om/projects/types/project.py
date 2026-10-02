"""A project: a tenant's unit of work, bound to one repository. The
policies the platform keys by project (what validates a change, where a
workspace may reach, which secrets a command sees, retention's narrowing)
are read through the project a session belongs to, and the session's own
branch and pull request are work product on this repository alone.

A project is written once. Its repository never moves, so the work product
of every session already in it stays where it was."""

from pydantic import Field, field_validator

from acme.om.base import Identifiable, Platform, Trackable
from acme.om.steps.types.content import Stored

MAX_PROJECT_NAME = 200

HOST = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
"""A source-control host by its domain name, such as `github.com`."""

REPOSITORY_PATH = r"^[a-z0-9_][a-z0-9_.-]*(/[a-z0-9_][a-z0-9_.-]*)+$"
"""A repository's path on its host: an owner, any groups, and a name, such
as `acme/arm`. No segment starts with a dot, so none is `.` or `..`."""


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


class Project(Identifiable, Trackable):
    """A tenant's project: its name, and the one repository it binds."""

    name: Stored = Field(min_length=1, max_length=MAX_PROJECT_NAME)
    repository: Repository
