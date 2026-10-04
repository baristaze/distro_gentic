"""The wire types of a validation session: one check of a project's policy,
asked for at a delivered commit and run on a fresh executor with no agent,
and its verdict once its run is recorded."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.platform_agents.types.validation import CHECK, COMMIT, ValidationStatus
from acme.services.api.types.common import RequestBody, View
from acme.services.api.types.evidence import ExecutionView


class StartValidationRequest(RequestBody):
    """A check the project's policy declares, to run at `head`, the delivered
    commit, with the checks, fixtures, and runner taken from `base`. Each is
    a commit's full id, never a name that moves."""

    project_id: UUID
    check: str = Field(pattern=CHECK)
    head: str = Field(pattern=COMMIT)
    base: str = Field(pattern=COMMIT)


class ValidationSessionView(View):
    """A validation session: what it runs, at which commit and from which,
    and where it stands. Once its run is recorded, `passed` is the verdict
    (the run passed, and at least one of its cases did) and `run` is that
    run; both are null while it waits."""

    id: UUID
    created_at: datetime
    created_by: UUID
    project_id: UUID
    check: str
    head: str
    base: str
    status: ValidationStatus
    finished_at: datetime | None
    passed: bool | None
    run: ExecutionView | None
