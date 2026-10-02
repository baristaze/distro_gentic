"""The wire types of stations: a tenant's labs, pools, and stations, the
credential that lets a lab's daemon in, the line and a place in it, a
lease, and a job; and what a daemon sends and is handed. A daemon's
requests carry no lab, no tenant, and no lane: those are its
credential's. Nothing here carries a station's limits: they are its
owner's, on its host."""

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.evidence.types.provenance import Provenance
from acme.om.evidence.types.record import NAME, PROJECT, VERSION, RunOutcome
from acme.om.stations.types.job import MAX_COMMANDS, RefusalReason, report_refusal
from acme.om.stations.types.station import Capability
from acme.services.api.types.common import RequestBody, View


class CreateLabRequest(RequestBody):
    name: str = Field(min_length=1, max_length=64)


class LabView(View):
    id: UUID
    name: str
    created_at: datetime
    created_by: UUID


class CreateStationPoolRequest(RequestBody):
    """`job_seconds` is the declared length of one holding, which a place's
    estimate reads."""

    name: str = Field(min_length=1, max_length=64)
    job_seconds: int = Field(default=600, ge=1, le=7 * 24 * 3600)


class StationPoolView(View):
    id: UUID
    name: str
    job_seconds: int
    created_at: datetime
    created_by: UUID


class CreateStationRequest(RequestBody):
    """A station of a lab, in a pool. `hold_seconds` is how long a lease
    outlives a job while its session is parked. No limit of the station's
    travels here: they are its owner's, on its host."""

    lab_id: UUID
    pool_id: UUID
    name: str = Field(min_length=1, max_length=64)
    capabilities: list[Capability] = Field(default_factory=list[Capability], max_length=32)
    hold_seconds: int = Field(default=300, ge=1, le=24 * 3600)


class StationView(View):
    """A station, with the highest fencing token granted on it and the
    lease that holds it, while one does."""

    id: UUID
    lab_id: UUID
    pool_id: UUID
    name: str
    capabilities: list[str]
    hold_seconds: int
    fencing_token: int
    lease_id: UUID | None
    held_until: datetime | None
    created_at: datetime


class IssuedDaemonCredentialView(View):
    """The lab daemon's credential in the clear, once: it lives a day, for
    its owner to install it, and the daemon rotates it from then on."""

    secret_fields = frozenset({"token"})

    token: str | None
    credential_id: UUID
    lab_id: UUID
    expires_at: datetime


class RevokedDaemonView(View):
    lab_id: UUID
    credentials_ended: int


class JoinLineRequest(RequestBody):
    """A session's ask: one station of the pool, or any that serves, with
    the capabilities it needs; and what it binds, the candidate under test,
    the procedure, and its version."""

    session_id: UUID
    station_id: UUID | None = None
    capabilities: list[Capability] = Field(default_factory=list[Capability], max_length=32)
    project: str = Field(pattern=PROJECT)
    candidate: str = Field(pattern=VERSION)
    procedure: str = Field(pattern=NAME)
    procedure_version: str = Field(pattern=VERSION)


class LineEntryView(View):
    id: UUID
    session_id: UUID
    pool_id: UUID
    station_id: UUID | None
    capabilities: list[str]
    project: str
    candidate: str
    procedure: str
    procedure_version: str
    state: str
    lease_id: UUID | None
    created_at: datetime


class LinePlaceView(View):
    """An entry, how many wait ahead of it, and the estimate of its wait."""

    entry: LineEntryView
    position: int
    estimate_seconds: int


class ReorderRequest(RequestBody):
    """The waiting entry this one goes ahead of, or null for the end."""

    before: UUID | None


class LeftLinesView(View):
    session_id: UUID
    left: int


class LeaseView(View):
    id: UUID
    station_id: UUID
    lab_id: UUID
    session_id: UUID
    fencing_token: int
    expires_at: datetime
    ended_at: datetime | None
    ended: str | None
    created_at: datetime


class CommandBody(RequestBody):
    """One operation for the station's adapter, with its parameters: data,
    never code."""

    operation: str = Field(pattern=NAME)
    parameters: dict[str, Any] = Field(default_factory=dict[str, Any])


class SubmitJobRequest(RequestBody):
    commands: list[CommandBody] = Field(min_length=1, max_length=MAX_COMMANDS)


class CommandView(View):
    operation: str
    parameters: dict[str, Any]


class StationJobView(View):
    """A job under a lease: its station and token are the lease's, and what
    it runs the lease's ask bound."""

    id: UUID
    lease_id: UUID
    station_id: UUID
    lab_id: UUID
    session_id: UUID
    fencing_token: int
    project: str
    candidate: str
    procedure: str
    procedure_version: str
    commands: list[CommandView]
    state: str
    run_id: UUID | None
    finished_at: datetime | None
    created_at: datetime


class StationClaimRequest(RequestBody):
    """The version of `station` work the daemon reads, and nothing else:
    what it is handed is its identity's to say."""

    station_version: int = Field(ge=1)


class ClaimedStationWorkView(View):
    """One item a daemon was handed, as `station` work of `wire_version`."""

    id: UUID
    kind: str
    target_id: UUID
    payload: dict[str, Any]
    lease_expires_at: datetime | None
    attempts: int
    wire_version: int


class StationClaimView(View):
    """What a claim answers: the item, the job it names, and how many
    seconds the job's lease has left, which the daemon times on its own
    monotonic clock. No item when nothing is ready; no job for an item that
    names none."""

    item: ClaimedStationWorkView | None
    job: StationJobView | None = None
    lease_seconds: float = 0


class LeaseTimeView(View):
    lease_id: UUID
    fencing_token: int
    seconds: float


class RefusalBody(RequestBody):
    operation: str = Field(min_length=1, max_length=100)
    reason: RefusalReason
    detail: str = Field(min_length=1, max_length=500)
    refused_at: datetime


class CaseTallyBody(RequestBody):
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)


class JobReportRequest(RequestBody):
    """What the daemon says of a job it ran. `run_id` is the daemon's, so a
    retried report lands once. A run a refusal ended is `aborted`, names
    the refusal in `abort`, and lists every refused command."""

    run_id: UUID
    outcome: RunOutcome
    started_at: datetime
    finished_at: datetime
    commands_run: int = Field(ge=0, le=MAX_COMMANDS)
    cases: CaseTallyBody = Field(default_factory=CaseTallyBody)
    refused: list[RefusalBody] = Field(default_factory=list[RefusalBody], max_length=MAX_COMMANDS)
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
