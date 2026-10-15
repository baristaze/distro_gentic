"""The two credentials the platform reaches an agent project's repository with, and
the agent never holds. A fetch credential reads the repository an agent project
binds, held in the tenant's store under the agent project; the platform uses it
where it reads a session's work product, outside every workspace. A push
token writes a session's own branch and its pull request, and nothing
else, for one loop at most; only its digest is kept."""

from datetime import datetime
from typing import ClassVar

from pydantic import Field, SecretStr

from acme.om.base import Identifiable, OmBase, Trackable


class FetchCredential(OmBase):
    """A read-only credential of the repository an agent project binds, as source
    control takes it over HTTPS: a user name and a password or token."""

    username: str = Field(min_length=1, max_length=200, pattern=r"^[^:\s]+$")
    password: SecretStr = Field(min_length=1, max_length=4096)


class RepositoryCredential(Identifiable, Trackable):
    """That an agent project's repository has a fetch credential, and who gave it
    when: one row an agent project, under the agent project's id. Its value is in the
    tenant's store, never here."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = ("version",)

    version: int = Field(default=1, ge=1)


class PushToken(OmBase):
    """A token that writes the session's own branch, its snapshots, and its
    pull request on the repository its agent project binds, until it expires or
    the loop's workspace goes, whichever is first."""

    token: SecretStr
    repository: str
    branch: str
    expires_at: datetime
