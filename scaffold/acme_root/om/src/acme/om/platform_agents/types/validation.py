"""A validation session: one check of a delivery run with no agent at all,
on a fresh executor. It is work on the same queue an agent's work takes,
and its run is the same execution record an agent's validation writes. The
session holds which of its project's checks it runs, at which commit and
from which protected source, and, once the run is recorded, which record
it is."""

from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import Identifiable, Platform, Trackable

CHECK = r"^[a-z][a-z0-9_.-]{0,99}$"
"""A check's name, as its project's policy declares it."""
COMMIT = r"^([0-9a-f]{40}|[0-9a-f]{64})$"
"""A commit's full id: a check runs at a commit, never at a name that moves."""


class ValidationStatus(StrEnum):
    QUEUED = "queued"  # its work waits on the queue, or runs on the executor
    FINISHED = "finished"  # its run is recorded


class ValidationStart(Platform):
    """A check of a project's policy to run at `head`, the delivered commit,
    with the checks, fixtures, and runner taken from `base`, where the work
    started. `id` is the caller's, so a start asked again answers the
    session it made."""

    id: UUID
    project_id: UUID
    check_name: str = Field(pattern=CHECK)
    head: str = Field(pattern=COMMIT)
    base: str = Field(pattern=COMMIT)


class ValidationSession(Identifiable, Trackable):
    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = (
        "status",
        "run_id",
        "finished_at",
        "version",
    )

    project_id: UUID
    check_name: str = Field(pattern=CHECK)
    head: str = Field(pattern=COMMIT)
    base: str = Field(pattern=COMMIT)
    status: ValidationStatus = ValidationStatus.QUEUED
    # The execution record of its run, once the run is recorded: a rated
    # check's last trial, whose validation holds the whole batch.
    run_id: UUID | None = None
    finished_at: datetime | None = None
    # Every write after the create is a compare-and-set on it.
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _a_finished_session_names_its_run(self) -> Self:
        finished = self.status is ValidationStatus.FINISHED
        if finished != (self.run_id is not None) or finished != (self.finished_at is not None):
            raise ValueError("a finished session names its run and when, and only a finished one")
        return self
