from uuid import UUID

from acme.om.base import thaw_mapping, utcnow
from acme.om.context import RequestContext, TenantContext
from acme.om.evidence.types.record import CaseTally
from acme.om.hosts.rules import WIRE_VERSION, WireType
from acme.om.stations import StationsManagerInterface
from acme.om.stations.types.daemon import DaemonIdentity, IssuedDaemonCredential
from acme.om.stations.types.job import JobReport, Refusal, StationCommand, StationJob
from acme.om.stations.types.lease import StationLease
from acme.om.stations.types.line import LinePlace, StationAsk
from acme.om.stations.types.station import Lab, Station, StationPool
from acme.services.api.services.stations import StationsServiceInterface
from acme.services.api.types.stations import (
    ClaimedStationWorkView,
    CommandView,
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
    LineEntryView,
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


def station_view(station: Station) -> StationView:
    return StationView(
        id=station.id,
        lab_id=station.lab_id,
        pool_id=station.pool_id,
        name=station.name,
        capabilities=list(station.capabilities),
        hold_seconds=station.hold_seconds,
        fencing_token=station.token,
        lease_id=station.lease_id,
        held_until=station.held_until,
        created_at=station.created_at,
    )


def place_view(placed: LinePlace) -> LinePlaceView:
    entry = placed.entry
    return LinePlaceView(
        entry=LineEntryView(
            id=entry.id,
            session_id=entry.session_id,
            pool_id=entry.pool_id,
            station_id=entry.station_id,
            capabilities=list(entry.capabilities),
            project=entry.project,
            candidate=entry.candidate,
            procedure=entry.procedure,
            procedure_version=entry.procedure_version,
            state=entry.state.value,
            lease_id=entry.lease_id,
            created_at=entry.created_at,
        ),
        position=placed.position,
        estimate_seconds=placed.estimate_seconds,
    )


def lease_view(lease: StationLease) -> LeaseView:
    return LeaseView(
        id=lease.id,
        station_id=lease.station_id,
        lab_id=lease.lab_id,
        session_id=lease.session_id,
        fencing_token=lease.token,
        expires_at=lease.expires_at,
        ended_at=lease.ended_at,
        ended=None if lease.ended is None else lease.ended.value,
        created_at=lease.created_at,
    )


def job_view(job: StationJob) -> StationJobView:
    return StationJobView(
        id=job.id,
        lease_id=job.lease_id,
        station_id=job.station_id,
        lab_id=job.lab_id,
        session_id=job.session_id,
        fencing_token=job.token,
        project=job.project,
        candidate=job.candidate,
        procedure=job.procedure,
        procedure_version=job.procedure_version,
        commands=[
            CommandView(operation=command.operation, parameters=thaw_mapping(command.parameters))
            for command in job.commands
        ],
        state=job.state.value,
        run_id=job.run_id,
        finished_at=job.finished_at,
        created_at=job.created_at,
    )


def credential_view(issued: IssuedDaemonCredential) -> IssuedDaemonCredentialView:
    return IssuedDaemonCredentialView(
        token=issued.credential,
        credential_id=issued.credential_id,
        lab_id=issued.lab_id,
        expires_at=issued.expires_at,
    )


class StationsServiceImpl(StationsServiceInterface):
    def __init__(self, stations: StationsManagerInterface) -> None:
        self._stations = stations

    async def create_lab(self, ctx: TenantContext, body: CreateLabRequest, lab_id: UUID) -> LabView:
        now = utcnow()
        lab = await self._stations.create_lab(
            ctx,
            Lab(
                id=lab_id,
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                name=body.name,
            ),
        )
        return LabView(
            id=lab.id, name=lab.name, created_at=lab.created_at, created_by=lab.created_by
        )

    async def create_pool(
        self, ctx: TenantContext, body: CreateStationPoolRequest, pool_id: UUID
    ) -> StationPoolView:
        now = utcnow()
        pool = await self._stations.create_pool(
            ctx,
            StationPool(
                id=pool_id,
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                name=body.name,
                job_seconds=body.job_seconds,
            ),
        )
        return StationPoolView(
            id=pool.id,
            name=pool.name,
            job_seconds=pool.job_seconds,
            created_at=pool.created_at,
            created_by=pool.created_by,
        )

    async def add_station(
        self, ctx: TenantContext, body: CreateStationRequest, station_id: UUID
    ) -> StationView:
        now = utcnow()
        station = Station(
            id=station_id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            lab_id=body.lab_id,
            pool_id=body.pool_id,
            name=body.name,
            capabilities=tuple(body.capabilities),
            hold_seconds=body.hold_seconds,
        )
        return station_view(await self._stations.add_station(ctx, station))

    async def get_stations(self, ctx: TenantContext, pool_id: UUID) -> list[StationView]:
        return [station_view(s) for s in await self._stations.get_stations(ctx, pool_id)]

    async def issue_daemon_credential(
        self, ctx: TenantContext, lab_id: UUID
    ) -> IssuedDaemonCredentialView:
        return credential_view(await self._stations.issue_daemon_credential(ctx, lab_id))

    async def revoke_daemon(self, ctx: TenantContext, lab_id: UUID) -> RevokedDaemonView:
        ended = await self._stations.revoke_daemon(ctx, lab_id)
        return RevokedDaemonView(lab_id=lab_id, credentials_ended=ended)

    async def join(
        self, ctx: TenantContext, pool_id: UUID, body: JoinLineRequest, entry_id: UUID
    ) -> LinePlaceView:
        ask = StationAsk(
            session_id=body.session_id,
            pool_id=pool_id,
            station_id=body.station_id,
            capabilities=tuple(body.capabilities),
            project=body.project,
            candidate=body.candidate,
            procedure=body.procedure,
            procedure_version=body.procedure_version,
        )
        return place_view(await self._stations.join(ctx, entry_id, ask))

    async def get_line(self, ctx: TenantContext, pool_id: UUID) -> list[LinePlaceView]:
        return [place_view(placed) for placed in await self._stations.get_line(ctx, pool_id)]

    async def reorder(
        self, ctx: TenantContext, entry_id: UUID, body: ReorderRequest
    ) -> LinePlaceView:
        return place_view(await self._stations.reorder(ctx, entry_id, body.before))

    async def leave(self, ctx: TenantContext, session_id: UUID) -> LeftLinesView:
        left = await self._stations.leave(ctx, session_id)
        return LeftLinesView(session_id=session_id, left=left)

    async def release_lease(self, ctx: TenantContext, lease_id: UUID) -> LeaseView:
        return lease_view(await self._stations.release_lease(ctx, lease_id))

    async def revoke_lease(self, ctx: TenantContext, lease_id: UUID) -> LeaseView:
        return lease_view(await self._stations.revoke_lease(ctx, lease_id))

    async def submit_job(
        self, ctx: TenantContext, lease_id: UUID, body: SubmitJobRequest, job_id: UUID
    ) -> StationJobView:
        commands = [
            StationCommand(operation=command.operation, parameters=command.parameters)
            for command in body.commands
        ]
        return job_view(await self._stations.submit_job(ctx, job_id, lease_id, commands))

    async def rotate(
        self, rctx: RequestContext, daemon: DaemonIdentity
    ) -> IssuedDaemonCredentialView:
        return credential_view(await self._stations.rotate(rctx, daemon))

    async def claim(
        self, rctx: RequestContext, daemon: DaemonIdentity, body: StationClaimRequest
    ) -> StationClaimView:
        claimed = await self._stations.claim(rctx, daemon, body.station_version)
        if claimed is None:
            return StationClaimView(item=None)
        item = claimed.item
        return StationClaimView(
            item=ClaimedStationWorkView(
                id=item.id,
                kind=item.kind.value,
                target_id=item.target_id,
                payload=thaw_mapping(item.payload),
                lease_expires_at=item.lease_expires_at,
                attempts=item.attempts,
                wire_version=WIRE_VERSION[WireType.STATION],
            ),
            job=None if claimed.job is None else job_view(claimed.job),
            lease_seconds=claimed.lease_seconds,
        )

    async def renew(
        self, rctx: RequestContext, daemon: DaemonIdentity, job_id: UUID
    ) -> LeaseTimeView:
        left = await self._stations.renew(rctx, daemon, job_id)
        return LeaseTimeView(lease_id=left.lease_id, fencing_token=left.token, seconds=left.seconds)

    async def report(
        self, rctx: RequestContext, daemon: DaemonIdentity, job_id: UUID, body: JobReportRequest
    ) -> StationJobView:
        report = JobReport(
            run_id=body.run_id,
            outcome=body.outcome,
            started_at=body.started_at,
            finished_at=body.finished_at,
            commands_run=body.commands_run,
            cases=CaseTally(
                passed=body.cases.passed, failed=body.cases.failed, skipped=body.cases.skipped
            ),
            refused=tuple(
                Refusal(
                    operation=refusal.operation,
                    reason=refusal.reason,
                    detail=refusal.detail,
                    refused_at=refusal.refused_at,
                )
                for refusal in body.refused
            ),
            abort=body.abort,
            adapter=body.adapter,
            provenance=body.provenance,
            daemon_version=body.daemon_version,
        )
        return job_view(await self._stations.report(rctx, daemon, job_id, report))
