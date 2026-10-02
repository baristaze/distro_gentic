"""A station job: what a session sends a station under its lease, and what
the daemon says of it once it ran. A job is data, a list of operations
for the station's adapter, never code: nothing a job holds runs inside
the daemon. Its run is an execution record like every other run, and a
command the station's guard refused is written into it."""

from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import FrozenMapping, Identifiable, Platform, Trackable
from acme.om.evidence.types.provenance import Provenance
from acme.om.evidence.types.record import NAME, PROJECT, VERSION, CaseTally, RunOutcome
from acme.om.work.types.work_item import WorkItem

MAX_COMMANDS = 100


class StationCommand(Platform):
    """One operation for the station's adapter, with its parameters."""

    operation: str = Field(pattern=NAME)
    parameters: FrozenMapping = Field(default_factory=dict, validate_default=True)


class JobState(StrEnum):
    QUEUED = "queued"  # its work waits on its lab's lane
    RUNNING = "running"  # its lab's daemon claimed it
    FINISHED = "finished"  # its run is recorded


class StationJob(Identifiable, Trackable):
    """A job under one lease, bound to what the lease's ask bound: the
    candidate, the procedure, and the token are the store's, never the
    sender's. `claim` is the work item the daemon claimed, kept so the
    report settles that claim and no other."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = (
        "state",
        "claim",
        "run_id",
        "finished_at",
    )

    lease_id: UUID
    station_id: UUID
    lab_id: UUID
    session_id: UUID
    token: int = Field(ge=1)
    project: str = Field(pattern=PROJECT)
    candidate: str = Field(pattern=VERSION)
    procedure: str = Field(pattern=NAME)
    procedure_version: str = Field(pattern=VERSION)
    commands: tuple[StationCommand, ...] = Field(min_length=1, max_length=MAX_COMMANDS)
    state: JobState = JobState.QUEUED
    claim: FrozenMapping | None = None
    run_id: UUID | None = None
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def _a_finished_job_names_its_run(self) -> Self:
        finished = self.state is JobState.FINISHED
        if finished != (self.run_id is not None) or finished != (self.finished_at is not None):
            raise ValueError("a finished job names its run and when, and only a finished one")
        return self


class RefusalReason(StrEnum):
    """Why the daemon did not run a command."""

    FENCED = "fenced"  # its token is below the highest the daemon has seen
    LIMIT = "limit"  # a parameter is past one of the station's limits
    UNKNOWN_OPERATION = "unknown_operation"  # the station does not accept the operation
    LEASE_ENDED = "lease_ended"  # its lease ran out, or was revoked


class Refusal(Platform):
    """One command the daemon refused, and why, in its own words."""

    operation: str = Field(min_length=1, max_length=100)
    reason: RefusalReason
    detail: str = Field(min_length=1, max_length=500)
    refused_at: datetime


class JobReport(Platform):
    """What the daemon says of a job it ran: its run's id, which it mints so
    a retried report lands once, its outcome and timing, the commands it
    ran, every command it refused, and what served the run. A run a refusal
    ended is `aborted`, and names the refusal."""

    run_id: UUID
    outcome: RunOutcome
    started_at: datetime
    finished_at: datetime
    commands_run: int = Field(ge=0, le=MAX_COMMANDS)
    cases: CaseTally = Field(default_factory=CaseTally)
    refused: tuple[Refusal, ...] = Field(default=(), max_length=MAX_COMMANDS)
    abort: str | None = Field(default=None, min_length=1, max_length=500)
    adapter: str = Field(min_length=1, max_length=200)
    provenance: Provenance
    daemon_version: str = Field(pattern=VERSION)

    @model_validator(mode="after")
    def _a_refusal_aborts(self) -> Self:
        refusal = report_refusal(
            self.outcome,
            self.abort,
            len(self.refused),
            self.cases.failed,
            self.started_at,
            self.finished_at,
        )
        if refusal is not None:
            raise ValueError(refusal)
        return self


def report_refusal(
    outcome: RunOutcome,
    abort: str | None,
    refused: int,
    failed_cases: int,
    started_at: datetime,
    finished_at: datetime,
) -> str | None:
    """Why a job's report cannot stand as a run's record, or None when it
    can: a run a refusal ended is aborted and names what stopped it, only an
    aborted one names anything, a run with a failed case did not pass, and
    a run finishes after it starts."""
    if (outcome is RunOutcome.ABORTED) != (abort is not None):
        return "an aborted run names what stopped it, and only an aborted one"
    if refused and outcome is not RunOutcome.ABORTED:
        return "a run with a refused command is aborted"
    if failed_cases and outcome is RunOutcome.PASSED:
        return "a run with a failed case did not pass"
    if finished_at < started_at:
        return "a run finishes after it starts"
    return None


class ClaimedJob(Platform):
    """What a daemon's claim answers: the item, and the job it names with
    how long its lease has left. `job` is None for an item that names no
    station job."""

    item: WorkItem
    job: StationJob | None = None
    lease_seconds: float = Field(default=0, ge=0)
