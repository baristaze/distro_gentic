"""A validation session: one check run on a station with no agent at all.
It is work on the same queue an agent's station work takes, and its run is
the same execution record an agent's run is. The session holds what the
daemon runs and where, and, once the run is recorded, which record it is."""

from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import FrozenMapping, Identifiable, Platform, Trackable

CHECK = r"^[a-z][a-z0-9_.-]{0,99}$"
"""A check's name."""
CHECK_VERSION = r"^\S{1,200}$"
"""A check's version: a commit, a tag, a digest. No whitespace."""


class ValidationStatus(StrEnum):
    QUEUED = "queued"  # its station work waits on its lab's lane, or runs there
    FINISHED = "finished"  # its run is recorded


class ValidationStart(Platform):
    """A check to run on a station of a lab. `id` is the caller's, so a
    start asked again answers the session it made."""

    id: UUID
    lab_id: UUID
    check_name: str = Field(pattern=CHECK)
    check_version: str = Field(pattern=CHECK_VERSION)
    parameters: FrozenMapping = Field(default_factory=dict, validate_default=True)


class ValidationSession(Identifiable, Trackable):
    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = (
        "status",
        "run_id",
        "finished_at",
        "version",
    )

    lab_id: UUID
    check_name: str = Field(pattern=CHECK)
    check_version: str = Field(pattern=CHECK_VERSION)
    parameters: FrozenMapping = Field(default_factory=dict, validate_default=True)
    status: ValidationStatus = ValidationStatus.QUEUED
    # The execution record of its run, once the daemon's run is recorded.
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
