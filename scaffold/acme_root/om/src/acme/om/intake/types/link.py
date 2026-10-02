"""The two facts the router reads to place an event: which user of the
tenant an outside account is, and which session a pull request or a branch
is the work of."""

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from acme.om.base import Created, Identifiable
from acme.om.steps.types.content import MAX_NAME, Stored


class AccountLink(Identifiable, Created):
    """An account in an integration's system, mapped to a user of the
    tenant. Only a mapped user may instruct a session from outside, or
    approve a call from chat. One link an account in a tenant."""

    integration: Stored = Field(min_length=1, max_length=MAX_NAME)
    external_id: Stored = Field(min_length=1, max_length=MAX_NAME)
    user_id: UUID
    created_by: UUID


class HandleKind(StrEnum):
    PULL_REQUEST = "pull_request"
    BRANCH = "branch"


class WorkBinding(Identifiable, Created):
    """A pull request or a branch that is a session's work, as the session
    opened it. One session a handle in a tenant."""

    session_id: UUID
    kind: HandleKind
    handle: Stored = Field(min_length=1, max_length=MAX_NAME)
