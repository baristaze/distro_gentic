"""Station routes. A tenant's: its labs, pools, and stations, its daemons'
credentials, the line, leases, and jobs. A lab daemon's own: rotate its
credential, claim its lab's work, renew the lease of the job it runs, and
report the run. Each function is one call into the stations service."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.services.api.gateway.auth import Ctx, Rctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.resolve import StationsService
from acme.services.api.gateway.stations import Daemon
from acme.services.api.types.stations import (
    CreateLabRequest,
    CreateStationPoolRequest,
    CreateStationRequest,
    IssuedDaemonCredentialView,
    JobReportRequest,
    JoinLineRequest,
    LabView,
    LeaseTimeView,
    LeaseView,
    LeftLinesView,
    LinePlaceView,
    ReorderRequest,
    RevokedDaemonView,
    StationClaimRequest,
    StationClaimView,
    StationJobView,
    StationPoolView,
    StationView,
    SubmitJobRequest,
)

router = APIRouter(tags=["stations"])


@router.post("/labs", response_model=LabView, status_code=201)
async def create_lab(
    ctx: Ctx, stations: StationsService, body: CreateLabRequest, idem: Idem
) -> Response:
    """A lab, the place one station daemon serves. An owner's or an admin's."""
    return await idem.run(201, lambda attempt: stations.create_lab(ctx, body, attempt.target_id))


@router.post("/station-pools", response_model=StationPoolView, status_code=201)
async def create_pool(
    ctx: Ctx, stations: StationsService, body: CreateStationPoolRequest, idem: Idem
) -> Response:
    """A pool of stations of one kind, with its line."""
    return await idem.run(201, lambda attempt: stations.create_pool(ctx, body, attempt.target_id))


@router.post("/stations", response_model=StationView, status_code=201)
async def add_station(
    ctx: Ctx, stations: StationsService, body: CreateStationRequest, idem: Idem
) -> Response:
    """A station of a lab, in a pool. Its limits are not sent: they are its
    owner's, on its host."""
    return await idem.run(201, lambda attempt: stations.add_station(ctx, body, attempt.target_id))


@router.get("/station-pools/{pool_id}/stations", response_model=list[StationView])
async def get_stations(ctx: Ctx, stations: StationsService, pool_id: UUID) -> list[StationView]:
    """The pool's stations, each with the lease that holds it."""
    return await stations.get_stations(ctx, pool_id)


@router.post("/labs/{lab_id}/daemon-credentials", response_model=IssuedDaemonCredentialView)
async def issue_daemon_credential(
    ctx: Ctx, stations: StationsService, lab_id: UUID
) -> IssuedDaemonCredentialView:
    """The lab daemon's first credential, in the clear once. A retry mints
    another, so it takes no Idempotency-Key; the one never read ends on its
    own."""
    return await stations.issue_daemon_credential(ctx, lab_id)


@router.delete("/labs/{lab_id}/daemon-credentials", response_model=RevokedDaemonView)
async def revoke_daemon(ctx: Ctx, stations: StationsService, lab_id: UUID) -> RevokedDaemonView:
    """Ends every credential of the lab's daemon at once."""
    return await stations.revoke_daemon(ctx, lab_id)


@router.post("/station-pools/{pool_id}/line", response_model=LinePlaceView, status_code=201)
async def join(
    ctx: Ctx, stations: StationsService, pool_id: UUID, body: JoinLineRequest, idem: Idem
) -> Response:
    """The session joins the pool's line, or one station's in it, and is
    told its place and an estimate."""
    return await idem.run(201, lambda attempt: stations.join(ctx, pool_id, body, attempt.target_id))


@router.get("/station-pools/{pool_id}/line", response_model=list[LinePlaceView])
async def get_line(ctx: Ctx, stations: StationsService, pool_id: UUID) -> list[LinePlaceView]:
    """The pool's line in the order it is served."""
    return await stations.get_line(ctx, pool_id)


@router.put("/line-entries/{entry_id}/place", response_model=LinePlaceView)
async def reorder(
    ctx: Ctx, stations: StationsService, entry_id: UUID, body: ReorderRequest
) -> LinePlaceView:
    """A person who manages the stations moves an entry in its line."""
    return await stations.reorder(ctx, entry_id, body)


@router.delete("/agent-sessions/{session_id}/line-entries", response_model=LeftLinesView)
async def leave(ctx: Ctx, stations: StationsService, session_id: UUID) -> LeftLinesView:
    """The session leaves every line it stands in."""
    return await stations.leave(ctx, session_id)


@router.post("/station-leases/{lease_id}/release", response_model=LeaseView)
async def release_lease(ctx: Ctx, stations: StationsService, lease_id: UUID) -> LeaseView:
    """The holding session lets the lease go; the station goes to the next
    in line."""
    return await stations.release_lease(ctx, lease_id)


@router.post("/station-leases/{lease_id}/revocation", response_model=LeaseView)
async def revoke_lease(ctx: Ctx, stations: StationsService, lease_id: UUID) -> LeaseView:
    """A person who manages the stations ends the lease; its session is
    told, and the station takes its controlled stop."""
    return await stations.revoke_lease(ctx, lease_id)


@router.post("/station-leases/{lease_id}/jobs", response_model=StationJobView, status_code=201)
async def submit_job(
    ctx: Ctx, stations: StationsService, lease_id: UUID, body: SubmitJobRequest, idem: Idem
) -> Response:
    """A job under a live lease, for the lab's daemon to claim."""
    return await idem.run(
        201, lambda attempt: stations.submit_job(ctx, lease_id, body, attempt.target_id)
    )


@router.post("/station-daemon/credentials", response_model=IssuedDaemonCredentialView)
async def rotate(
    rctx: Rctx, stations: StationsService, daemon: Daemon
) -> IssuedDaemonCredentialView:
    """The daemon's next credential; the one it called with ends after a
    short grace."""
    return await stations.rotate(rctx, daemon)


@router.post("/station-daemon/claims", response_model=StationClaimView)
async def claim(
    rctx: Rctx, stations: StationsService, daemon: Daemon, body: StationClaimRequest
) -> StationClaimView:
    """The next item of the daemon's lab, or none. The body states the
    version the daemon reads, and nothing it is handed."""
    return await stations.claim(rctx, daemon, body)


@router.post("/station-daemon/jobs/{job_id}/renewals", response_model=LeaseTimeView)
async def renew(
    rctx: Rctx, stations: StationsService, daemon: Daemon, job_id: UUID
) -> LeaseTimeView:
    """The lease of a job the daemon runs, renewed; 410 once it ended."""
    return await stations.renew(rctx, daemon, job_id)


@router.post("/station-daemon/jobs/{job_id}/reports", response_model=StationJobView)
async def report(
    rctx: Rctx, stations: StationsService, daemon: Daemon, job_id: UUID, body: JobReportRequest
) -> StationJobView:
    """The run of a job the daemon ran, its refused commands in it."""
    return await stations.report(rctx, daemon, job_id, body)
