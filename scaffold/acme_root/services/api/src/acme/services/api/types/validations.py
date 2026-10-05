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
    and `run` is that run; both are null while it waits. The run passes
    when it passed, at least one of its cases did, and what served it meets
    the strictest grade the project's policy asks of the check, a twin when
    no requirement names it: a run on a double, or with a dependency that
    was not there, never passes. A check a requirement rates runs its
    declared trials and passes only as that requirement judges them
    together, so one lucky trial never passes it; `run` is its last trial.
    `reason` says why it did not pass, and is null otherwise."""

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
    reason: str | None
    run: ExecutionView | None
