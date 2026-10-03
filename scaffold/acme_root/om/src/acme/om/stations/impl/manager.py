import contextlib
import logging
import secrets
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from acme.infra.observability import OUTCOMES
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.rules import unlock_step
from acme.om.attribution.rules import principal_of
from acme.om.base import Platform, new_id, utcnow
from acme.om.context import Permission, RequestContext, TenantContext
from acme.om.evidence import EvidenceManagerInterface
from acme.om.evidence.types.provenance import Dependency, Provenance
from acme.om.evidence.types.record import Environment, ExecutionRecord, RunOutcome, RunPurpose
from acme.om.exceptions import (
    CredentialExpired,
    InvalidCredential,
    LeaseLost,
    NotFound,
    PlatformException,
    ValidationFailed,
)
from acme.om.hosts.exceptions import VersionBelowFloor
from acme.om.hosts.rules import WIRE_FLOOR, WireType, at_or_above_floor
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, outbox_row
from acme.om.placement import PlacementManagerInterface
from acme.om.placement.types.claimant import Claimant, ClaimantKind
from acme.om.placement.types.work import StationPayload
from acme.om.platform_agents import PlatformAgentsManagerInterface
from acme.om.platform_agents.types.validation import ValidationSession, ValidationStatus
from acme.om.stations.exceptions import JobSettled, LeaseEnded
from acme.om.stations.manager import StationsManagerInterface
from acme.om.stations.rules import (
    DAEMON_CREDENTIAL_PREFIX,
    free,
    grant_text,
    in_line_order,
    no_longer_waits,
    place,
    rank_between,
    renewed_until,
    retired_at,
    revoke_text,
    seconds_left,
    serves,
    waits,
)
from acme.om.stations.storage import StationsStorageInterface
from acme.om.stations.types.daemon import (
    DaemonCredential,
    DaemonIdentity,
    IssuedDaemonCredential,
    Rotation,
)
from acme.om.stations.types.job import (
    ClaimedJob,
    JobReport,
    JobState,
    StationCommand,
    StationJob,
)
from acme.om.stations.types.lease import LeaseEnd, LeaseTime, StationLease
from acme.om.stations.types.line import EntryState, LineEntry, LinePlace, StationAsk
from acme.om.stations.types.station import Lab, Station, StationPool
from acme.om.steps.types.content import Content, TextBlock
from acme.om.steps.types.header import InputHeader
from acme.om.steps.types.step import Actor, Origin, Step, StepType
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tenancy.rules import hash_token
from acme.om.work import WorkManagerInterface
from acme.om.work.types.work_item import WorkItem, WorkKind, work_row_kind

log = logging.getLogger(__name__)

LAB_CREATED = "stations.lab.created"
POOL_CREATED = "stations.station_pool.created"
STATION_CREATED = "stations.station.created"
CREDENTIAL_ISSUED = "stations.daemon_credential.created"
DAEMON_REVOKED = "stations.daemon_credential.revoked"
ENTRY_CREATED = "stations.line_entry.created"
LEASE_GRANTED = "stations.station_lease.created"
LEASE_ENDED = "stations.station_lease.ended"
JOB_CREATED = "stations.station_job.created"
JOB_UPDATED = "stations.station_job.updated"


class StationsOptions(Platform):
    # A daemon's first credential lives a day, for its owner to install it;
    # every one it rotates to lives an hour, and the daemon rotates it at half
    # its life, so one taken from a disk is worth an hour at most.
    first_credential_ttl: timedelta = timedelta(days=1)
    credential_ttl: timedelta = timedelta(hours=1)
    # A rotated credential still works this long, so a call in flight with
    # it still lands. It rotates once: a second rotation revokes the daemon.
    rotation_grace: timedelta = timedelta(minutes=1)
    # A lease that ran out is granted again only this long after: it covers
    # the clocks of the processes that grant, and the way back of the answer
    # the daemon timed its lease from.
    skew_margin: timedelta = timedelta(seconds=30)
    # How long one renewal holds a station while a job runs; the daemon
    # renews at half of it.
    job_lease: timedelta = timedelta(seconds=60)
    # How long the daemon holds a claimed job's work item; renewed with the
    # lease.
    claim_lease: timedelta = timedelta(seconds=60)
    # How long a validation waits on its lab's lane when every station of
    # its lab is held, or waited for in line, before it is claimed again.
    validation_retry: timedelta = timedelta(seconds=30)
    grant_attempts: int = 3  # a grant lost to another writer is tried again this often
    max_line: int = 500  # the most entries of one pool's line read at once
    max_stations: int = 200  # the most stations of one pool read at once
    purge_batch: int = 1000


def mint() -> tuple[str, str]:
    """A fresh daemon credential, and the digest that is kept."""
    secret = DAEMON_CREDENTIAL_PREFIX + secrets.token_urlsafe(32)
    return secret, hash_token(secret)


class StationsManagerImpl(StationsManagerInterface):
    def __init__(
        self,
        storage: StationsStorageInterface,
        placement: PlacementManagerInterface,
        sessions: AgentSessionsManagerInterface,
        evidence: EvidenceManagerInterface,
        validations: PlatformAgentsManagerInterface,
        work: WorkManagerInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        options: StationsOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._placement = placement
        self._sessions = sessions
        self._evidence = evidence
        self._validations = validations
        self._work = work
        self._tenancy = tenancy
        self._relay = relay
        self._options = options
        self._clock = clock

    # What a tenant's stations are.

    async def create_lab(self, ctx: TenantContext, lab: Lab) -> Lab:
        ctx.require(Permission.MANAGE_MEMBERS)
        created = self._stamped(ctx, lab)
        rows = (outbox_row(ctx, LAB_CREATED, created.id, {}),)
        if not await self._storage.create_lab(ctx.org_id, created, rows):
            return await self._lab(ctx, created.id)
        await self._relay.relay_all(ctx.org_id, rows)
        return created

    async def create_pool(self, ctx: TenantContext, pool: StationPool) -> StationPool:
        ctx.require(Permission.MANAGE_MEMBERS)
        created = self._stamped(ctx, pool)
        rows = (outbox_row(ctx, POOL_CREATED, created.id, {}),)
        if not await self._storage.create_pool(ctx.org_id, created, rows):
            return await self._pool(ctx, created.id)
        await self._relay.relay_all(ctx.org_id, rows)
        return created

    async def add_station(self, ctx: TenantContext, station: Station) -> Station:
        ctx.require(Permission.MANAGE_MEMBERS)
        await self._lab(ctx, station.lab_id)
        await self._pool(ctx, station.pool_id)
        created = self._stamped(ctx, station).model_copy(
            update={"token": 0, "lease_id": None, "held_until": None}
        )
        rows = (
            outbox_row(
                ctx,
                STATION_CREATED,
                created.id,
                {"lab_id": str(created.lab_id), "pool_id": str(created.pool_id)},
            ),
        )
        if not await self._storage.create_station(ctx.org_id, created, rows):
            return await self._station(ctx, created.id)
        await self._relay.relay_all(ctx.org_id, rows)
        return created

    async def get_stations(self, ctx: TenantContext, pool_id: UUID) -> tuple[Station, ...]:
        ctx.require(Permission.READ)
        await self._pool(ctx, pool_id)
        return tuple(
            await self._storage.read_stations(ctx.org_id, pool_id, self._options.max_stations)
        )

    async def issue_daemon_credential(
        self, ctx: TenantContext, lab_id: UUID
    ) -> IssuedDaemonCredential:
        ctx.require(Permission.MANAGE_MEMBERS)
        await self._lab(ctx, lab_id)
        now = self._clock()
        secret, credential = self._credential(
            lab_id, ctx.user_id, now, self._options.first_credential_ttl
        )
        rows = (outbox_row(ctx, CREDENTIAL_ISSUED, credential.id, {"lab_id": str(lab_id)}),)
        await self._storage.create_daemon_credential(ctx.org_id, credential, rows)
        await self._relay.relay_all(ctx.org_id, rows)
        return self._issued(secret, credential)

    async def revoke_daemon(self, ctx: TenantContext, lab_id: UUID) -> int:
        ctx.require(Permission.MANAGE_MEMBERS)
        await self._lab(ctx, lab_id)
        rows = (outbox_row(ctx, DAEMON_REVOKED, lab_id, {}),)
        ended = await self._storage.revoke_daemon(ctx.org_id, lab_id, self._clock(), rows)
        await self._relay.relay_all(ctx.org_id, rows)
        return ended

    # The line.

    async def join(self, ctx: TenantContext, entry_id: UUID, ask: StationAsk) -> LinePlace:
        ctx.require(Permission.WRITE)
        await self._sessions.get_session(ctx, ask.session_id)
        return await self._join(ctx, entry_id, ask, ())

    async def join_with_job(
        self,
        ctx: TenantContext,
        entry_id: UUID,
        ask: StationAsk,
        commands: Sequence[StationCommand],
    ) -> LinePlace:
        ctx.require(Permission.WRITE)
        if not commands:
            raise ValidationFailed("an ask that carries its job carries at least one command")
        return await self._join(ctx, entry_id, ask, tuple(commands))

    async def get_entry(self, ctx: TenantContext, entry_id: UUID) -> LinePlace:
        ctx.require(Permission.READ)
        return await self._place(ctx, entry_id)

    async def get_job(self, ctx: TenantContext, job_id: UUID) -> StationJob:
        ctx.require(Permission.READ)
        job = await self._storage.read_job(ctx.org_id, job_id)
        if job is None:
            raise NotFound(f"station job {job_id} not found")
        return job

    async def _join(
        self,
        ctx: TenantContext,
        entry_id: UUID,
        ask: StationAsk,
        commands: tuple[StationCommand, ...],
    ) -> LinePlace:
        pool = await self._pool(ctx, ask.pool_id)
        named = None
        if ask.station_id is not None:
            named = await self._station(ctx, ask.station_id)
            if named.pool_id != pool.id:
                raise ValidationFailed(f"station {named.id} is not of pool {pool.id}")
        now = self._clock()
        entry = LineEntry(
            id=entry_id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            **ask.model_dump(),
            principal=principal_of(ctx),
            rank=now.timestamp(),
            commands=commands,
        )
        rows = (
            outbox_row(
                ctx,
                ENTRY_CREATED,
                entry.id,
                {"pool_id": str(pool.id), "session_id": str(ask.session_id)},
            ),
        )
        if await self._storage.create_entry(ctx.org_id, entry, rows):
            await self._relay.relay_all(ctx.org_id, rows)
            # A free station goes to the first in line that waits, which is
            # this entry only when nobody waits ahead of it.
            stations = (
                [named]
                if named is not None
                else await self._storage.read_stations(
                    ctx.org_id, pool.id, self._options.max_stations
                )
            )
            for station in stations:
                if serves(station, entry):
                    await self._offer(ctx, station.id)
        return await self._place(ctx, entry_id)

    async def get_line(self, ctx: TenantContext, pool_id: UUID) -> tuple[LinePlace, ...]:
        ctx.require(Permission.READ)
        pool = await self._pool(ctx, pool_id)
        line = await self._storage.read_line(ctx.org_id, pool_id, self._options.max_line)
        stations = await self._storage.read_stations(
            ctx.org_id, pool_id, self._options.max_stations
        )
        return tuple(self._placed(entry, line, stations, pool) for entry in line)

    async def reorder(self, ctx: TenantContext, entry_id: UUID, before: UUID | None) -> LinePlace:
        ctx.require(Permission.MANAGE_MEMBERS)
        entry = await self._storage.read_entry(ctx.org_id, entry_id)
        if entry is None or entry.state is not EntryState.WAITING:
            raise NotFound(f"no waiting entry {entry_id}")
        line = [
            other
            for other in await self._storage.read_line(
                ctx.org_id, entry.pool_id, self._options.max_line
            )
            if other.id != entry_id
        ]
        if before is None:
            rank = rank_between(line[-1].rank if line else None, None, entry.rank)
        else:
            at = next((i for i, other in enumerate(line) if other.id == before), None)
            if at is None:
                raise NotFound(f"no waiting entry {before} in the line of pool {entry.pool_id}")
            ahead = line[at - 1].rank if at > 0 else None
            rank = rank_between(ahead, line[at].rank, entry.rank)
        if not await self._storage.write_rank(
            ctx.org_id, entry_id, rank, self._clock(), ctx.user_id
        ):
            raise NotFound(f"no waiting entry {entry_id}")
        return await self._place(ctx, entry_id)

    async def offer_parked(self, ctx: TenantContext, session_id: UUID) -> StationLease | None:
        ctx.require(Permission.WRITE)
        offered: set[UUID] = set()
        waiting = await self._storage.read_waiting(ctx.org_id, session_id, self._options.max_line)
        for entry in waiting:
            if entry.station_id is not None:
                named = await self._storage.read_station(ctx.org_id, entry.station_id)
                stations = [] if named is None else [named]
            else:
                stations = await self._storage.read_stations(
                    ctx.org_id, entry.pool_id, self._options.max_stations
                )
            for station in stations:
                if station.id in offered or not serves(station, entry):
                    continue
                offered.add(station.id)
                lease = await self._offer(ctx, station.id)
                if lease is not None and lease.session_id == session_id:
                    return lease
        return None

    async def leave(self, ctx: TenantContext, session_id: UUID) -> int:
        ctx.require(Permission.WRITE)
        return await self._leave_every_line(ctx, session_id)

    # The leases.

    async def release_lease(self, ctx: TenantContext, lease_id: UUID) -> StationLease:
        ctx.require(Permission.WRITE)
        return await self._end(ctx, lease_id, LeaseEnd.RELEASED)

    async def revoke_lease(self, ctx: TenantContext, lease_id: UUID) -> StationLease:
        ctx.require(Permission.MANAGE_MEMBERS)
        ended = await self._end(ctx, lease_id, LeaseEnd.REVOKED)
        entry = (
            None
            if ended.entry_id is None
            else await self._storage.read_entry(ctx.org_id, ended.entry_id)
        )
        if entry is not None and not entry.commands:
            # The holding session reads it at its next request; an idle one
            # is not woken for it. An entry that carries its job has no
            # session to tell: its job's run records the stop.
            await self._tell(ctx, entry, revoke_text(ended), waking=False)
        return ended

    async def submit_job(
        self,
        ctx: TenantContext,
        job_id: UUID,
        lease_id: UUID,
        commands: Sequence[StationCommand],
    ) -> StationJob:
        ctx.require(Permission.WRITE)
        stored = await self._storage.read_job(ctx.org_id, job_id)
        if stored is not None:
            return stored
        lease = await self._storage.read_lease(ctx.org_id, lease_id)
        if lease is None:
            raise NotFound(f"lease {lease_id} not found")
        now = self._clock()
        if lease.ended_at is not None or lease.expires_at <= now:
            raise LeaseEnded(f"lease {lease_id} is no longer live")
        if lease.entry_id is None:
            raise ValidationFailed(
                f"lease {lease_id} is a validation session's, and runs its check alone"
            )
        entry = await self._storage.read_entry(ctx.org_id, lease.entry_id)
        if entry is None:
            raise NotFound(f"the ask of lease {lease_id} not found")
        if entry.commands:
            raise ValidationFailed(f"lease {lease_id} carries its own job, and runs it alone")
        job = StationJob(
            id=job_id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            lease_id=lease.id,
            station_id=lease.station_id,
            lab_id=lease.lab_id,
            session_id=lease.session_id,
            token=lease.token,
            project=entry.project,
            candidate=entry.candidate,
            procedure=entry.procedure,
            procedure_version=entry.procedure_version,
            commands=tuple(commands),
        )
        rows = self._job_rows(ctx, job)
        if not await self._storage.create_job(ctx.org_id, job, rows):
            found = await self._storage.read_job(ctx.org_id, job_id)
            if found is None:
                raise NotFound(f"station job {job_id} not found")
            return found
        await self._relay.relay_all(ctx.org_id, rows)
        return job

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    # A daemon's side.

    async def authenticate(self, rctx: RequestContext, credential: str) -> DaemonIdentity:
        if not credential.startswith(DAEMON_CREDENTIAL_PREFIX):
            raise InvalidCredential("a station daemon calls with its own credential")
        found = await self._storage.read_daemon_credential_by_digest(hash_token(credential))
        if found is None:
            raise InvalidCredential("unknown daemon credential")
        org_id, held = found
        if held.revoked_at is not None:
            raise CredentialExpired("daemon credential revoked")
        now = self._clock()
        if held.expires_at <= now:
            if held.rotated_at is not None:
                # A rotated credential past its grace: the daemon that rotated
                # it holds the next one, so whoever presents this one is a
                # second daemon, or the first is.
                await self._reused(rctx, org_id, held.lab_id, held.issued_by)
                raise CredentialExpired(
                    "daemon credential rotated already; the lab's daemon is revoked"
                )
            raise CredentialExpired("daemon credential expired")
        return DaemonIdentity(
            lab_id=held.lab_id,
            org_id=org_id,
            credential_id=held.id,
            issued_by=held.issued_by,
            expires_at=held.expires_at,
        )

    async def rotate(self, rctx: RequestContext, daemon: DaemonIdentity) -> IssuedDaemonCredential:
        now = self._clock()
        secret, minted = self._credential(
            daemon.lab_id, daemon.issued_by, now, self._options.credential_ttl
        )
        retire_at = retired_at(daemon.expires_at, now, self._options.rotation_grace)
        rotation = await self._storage.rotate_daemon_credential(
            daemon.org_id, daemon.credential_id, now, retire_at, minted
        )
        if rotation is Rotation.REUSED:
            await self._reused(rctx, daemon.org_id, daemon.lab_id, daemon.issued_by)
            raise CredentialExpired(
                "daemon credential rotated already; the lab's daemon is revoked"
            )
        if rotation is not Rotation.ROTATED:
            raise CredentialExpired("daemon credential expired, rotated, or revoked")
        return self._issued(secret, minted)

    async def claim(
        self, rctx: RequestContext, daemon: DaemonIdentity, station_version: int
    ) -> ClaimedJob | None:
        if not at_or_above_floor(WireType.STATION, station_version):
            OUTCOMES.labels(subsystem="stations", outcome="below_floor").inc()
            raise VersionBelowFloor(
                f"this daemon reads station work at version {station_version}; the platform "
                f"hands work to version {WIRE_FLOOR[WireType.STATION]} and later"
            )
        # The claimant is the identity the credential resolved to: the lab
        # and the tenant whose wall it sits in, and nothing the call names.
        claimant = Claimant(
            kind=ClaimantKind.DAEMON,
            id=daemon.lab_id,
            org_id=daemon.org_id,
            lab_id=daemon.lab_id,
        )
        while True:
            claimed = await self._placement.claim_for(rctx, claimant, self._options.claim_lease)
            if claimed is None:
                return None
            ctx, item = claimed
            job = await self._storage.read_job(ctx.org_id, item.target_id)
            if job is None:
                validation = await self._validation(ctx, item.target_id)
                if validation is None or validation.lab_id != daemon.lab_id:
                    return ClaimedJob(item=item)
                if validation.status is ValidationStatus.FINISHED:
                    await self._work.fail_for_good(
                        ctx, item, f"validation session {validation.id} runs its check once"
                    )
                    continue
                job = await self._validation_job(ctx, validation)
                if job is None:
                    # Every station of its lab is held, or a session waits in
                    # line for it: the validation waits its turn on its lane.
                    await self._work.defer(ctx, item, self._options.validation_retry)
                    continue
            if job.lab_id != daemon.lab_id:
                return ClaimedJob(item=item)
            now = self._clock()
            if job.state is JobState.RUNNING:
                # Its item is claimed again: the answer of the claim before
                # never reached the daemon, or the daemon lost the job. It is
                # settled by a run that reached no verdict, and never runs
                # twice.
                await self._interrupted(ctx, job, item, now)
                continue
            running = StationJob.model_validate(
                {
                    **job.model_dump(),
                    "state": JobState.RUNNING,
                    "claim": item.model_dump(mode="json"),
                    "updated_at": now,
                    "updated_by": ctx.user_id,
                }
            )
            rows = (outbox_row(ctx, JOB_UPDATED, job.id, {"state": JobState.RUNNING.value}),)
            if job.state is not JobState.QUEUED or not await self._storage.write_job(
                ctx.org_id, running, JobState.QUEUED, rows
            ):
                OUTCOMES.labels(subsystem="stations", outcome="job_claimed_again").inc()
                await self._work.fail_for_good(ctx, item, f"station job {job.id} runs once")
                continue
            await self._relay.relay_all(ctx.org_id, rows)
            # The job's hold starts at its claim, not when it was sent: a job
            # that waited on its lab's lane behind another station's keeps
            # its lease, unless a grant took its station meanwhile.
            seconds = await self._renewed(
                ctx.org_id, running, now, self._options.job_lease, lapsed=True
            )
            return ClaimedJob(item=item, job=running, lease_seconds=seconds or 0.0)

    async def renew(self, rctx: RequestContext, daemon: DaemonIdentity, job_id: UUID) -> LeaseTime:
        job = await self._running(daemon, job_id)
        now = self._clock()
        seconds = await self._renewed(daemon.org_id, job, now, self._options.job_lease)
        if seconds is None:
            raise LeaseEnded(f"the lease of station job {job_id} ran out or was ended")
        ctx = await self._tenancy.service_context(rctx, daemon.org_id, job.created_by)
        try:
            await self._work.extend_lease(ctx, self._claimed(job), self._options.claim_lease)
        except LeaseLost:
            log.warning("station job %s: its work item was taken back meanwhile", job.id)
        return LeaseTime(lease_id=job.lease_id, token=job.token, seconds=seconds)

    async def report(
        self, rctx: RequestContext, daemon: DaemonIdentity, job_id: UUID, report: JobReport
    ) -> StationJob:
        job = await self._storage.read_job(daemon.org_id, job_id)
        if job is None or job.lab_id != daemon.lab_id:
            raise NotFound(f"station job {job_id} not found")
        if job.state is JobState.FINISHED and job.run_id == report.run_id:
            return job
        if job.state is not JobState.RUNNING:
            raise JobSettled(f"station job {job_id} is {job.state.value}")
        ctx = await self._tenancy.service_context(rctx, daemon.org_id, job.created_by)
        finished = await self._settle(ctx, job, report, self._clock(), self._claimed(job))
        if finished is None:
            stored = await self._storage.read_job(daemon.org_id, job_id)
            if stored is not None and stored.run_id == report.run_id:
                return stored
            raise JobSettled(f"station job {job_id} was settled meanwhile")
        if report.refused:
            OUTCOMES.labels(subsystem="stations", outcome="command_refused").inc(
                len(report.refused)
            )
        return finished

    async def _settle(
        self, ctx: TenantContext, job: StationJob, report: JobReport, now: datetime, item: WorkItem
    ) -> StationJob | None:
        """A running job's run recorded and the job finished, its item
        complete, and its lease handed on: a validation's goes back to the
        line, and a session's lasts its station's hold time. None, with the
        job as it was, when it was settled meanwhile."""
        # The run is the evidence: its record is written once, with every
        # command the station's guard refused in it.
        await self._evidence.record_run(ctx, self._record(job, report, now))
        finished = job.model_copy(
            update={
                "state": JobState.FINISHED,
                "run_id": report.run_id,
                "finished_at": now,
                "updated_at": now,
                "updated_by": ctx.user_id,
            }
        )
        rows = (outbox_row(ctx, JOB_UPDATED, job.id, {"state": JobState.FINISHED.value}),)
        if not await self._storage.write_job(ctx.org_id, finished, JobState.RUNNING, rows):
            return None
        await self._relay.relay_all(ctx.org_id, rows)
        try:
            await self._work.complete(ctx, item)
        except LeaseLost:
            log.warning("station job %s: its work item was taken back before it settled", job.id)
        lease = await self._storage.read_lease(ctx.org_id, job.lease_id)
        if lease is not None and lease.entry_id is None:
            # A validation's run finishes its session, with no agent and no
            # model, and its station goes back to the line at once.
            await self._validations.finish_validation(ctx, job.session_id, report.run_id)
            with contextlib.suppress(LeaseEnded):
                await self._end(ctx, lease.id, LeaseEnd.RELEASED)
            return finished
        entry = (
            None
            if lease is None or lease.entry_id is None
            else await self._storage.read_entry(ctx.org_id, lease.entry_id)
        )
        if lease is not None and entry is not None and entry.commands:
            # A job its entry carried ran alone under its lease: the station
            # goes back to the line at once.
            with contextlib.suppress(LeaseEnded):
                await self._end(ctx, lease.id, LeaseEnd.RELEASED)
            return finished
        # Its session is parked again until its next job: the lease lasts
        # the station's hold time from here.
        station = await self._storage.read_station(ctx.org_id, job.station_id)
        if station is not None:
            await self._renewed(ctx.org_id, job, now, timedelta(seconds=station.hold_seconds))
        return finished

    async def _interrupted(
        self, ctx: TenantContext, job: StationJob, item: WorkItem, now: datetime
    ) -> None:
        """A running job whose item came back: its run is recorded as one
        that reached no verdict, which finishes a validation as
        inconclusive, and the item claimed now completes with it."""
        OUTCOMES.labels(subsystem="stations", outcome="job_interrupted").inc()
        report = JobReport(
            run_id=new_id(),
            outcome=RunOutcome.ERRORED,
            started_at=min(job.updated_at, now),
            finished_at=now,
            commands_run=0,
            adapter="none",
            provenance=Provenance.UNAVAILABLE,
            daemon_version="unreported",
        )
        if await self._settle(ctx, job, report, now, item) is None:
            await self._work.fail_for_good(ctx, item, f"station job {job.id} runs once")

    # The grant.

    async def _offer(self, ctx: TenantContext, station_id: UUID) -> StationLease | None:
        """Grants a free station to the first entry in line that waits, and
        wakes its session. An entry whose session no longer waits is passed,
        and that session leaves every line it stood in; one whose session
        has not parked yet keeps its place and is passed over. An entry that
        carries its job always waits, and its job lands with its grant. A
        grant lost to another writer reads the station again and goes on
        from it."""
        margin = self._options.skew_margin
        for _ in range(self._options.grant_attempts):
            station = await self._storage.read_station(ctx.org_id, station_id)
            now = self._clock()
            if station is None or not free(station, now, margin):
                return None
            line = await self._storage.read_line(
                ctx.org_id, station.pool_id, self._options.max_line
            )
            lost = False
            for entry in line:
                if not serves(station, entry):
                    continue
                if not entry.commands:
                    try:
                        session = await self._sessions.project_status(ctx, entry.session_id)
                    except NotFound:
                        session = None
                    if session is None or no_longer_waits(session):
                        await self._leave_every_line(ctx, entry.session_id)
                        continue
                    if not waits(session):
                        continue
                lease = StationLease(
                    id=new_id(),
                    created_at=now,
                    updated_at=now,
                    created_by=ctx.user_id,
                    updated_by=ctx.user_id,
                    station_id=station.id,
                    lab_id=station.lab_id,
                    pool_id=station.pool_id,
                    entry_id=entry.id,
                    session_id=entry.session_id,
                    token=station.token + 1,
                    expires_at=now + timedelta(seconds=station.hold_seconds),
                )
                # A carried job lands in the grant's own write: it never
                # stands without its lease, and its lease never waits on it.
                job = self._carried(entry, lease) if entry.commands else None
                rows = (
                    outbox_row(
                        ctx,
                        LEASE_GRANTED,
                        lease.id,
                        {"station_id": str(station.id), "token": lease.token},
                    ),
                    *(() if job is None else self._job_rows(ctx, job)),
                )
                if await self._storage.grant(ctx.org_id, lease, margin, rows, job):
                    await self._relay.relay_all(ctx.org_id, rows)
                    OUTCOMES.labels(subsystem="stations", outcome="granted").inc()
                    if job is None:
                        await self._tell(
                            ctx,
                            entry,
                            grant_text(station, lease, station.hold_seconds),
                            waking=True,
                        )
                    return lease
                lost = True
                break
            if not lost:
                return None
        return None

    async def _tell(self, ctx: TenantContext, entry: LineEntry, text: str, *, waking: bool) -> None:
        """An event in the session's history, on the authority of who asked.
        A waking one comes with the unlock its park waits for, so it is the
        grant that clears the park. The grant stands if the session cannot
        take it: its lease then runs out at its hold time."""
        now = self._clock()
        event_id = new_id()
        steps = [
            Step(
                id=event_id,
                created_at=now,
                session_id=entry.session_id,
                loop_id=event_id,
                type=StepType.EVENT,
                actor=Actor.EXTERNAL,
                origin=Origin.AUTOMATION,
                header=InputHeader(waking=waking, principal=entry.principal),
                content=Content(blocks=(TextBlock(text=text),)),
            )
        ]
        if waking:
            steps.append(unlock_step(new_id(), entry.session_id, now))
        try:
            await self._sessions.receive(ctx, entry.session_id, steps)
        except PlatformException as error:
            OUTCOMES.labels(subsystem="stations", outcome="session_not_told").inc()
            log.warning("session %s was not told of its lease: %s", entry.session_id, error)

    async def _end(self, ctx: TenantContext, lease_id: UUID, end: LeaseEnd) -> StationLease:
        rows = (outbox_row(ctx, LEASE_ENDED, lease_id, {"ended": end.value}),)
        ended = await self._storage.end_lease(ctx.org_id, lease_id, self._clock(), end, rows)
        if ended is None:
            if await self._storage.read_lease(ctx.org_id, lease_id) is None:
                raise NotFound(f"lease {lease_id} not found")
            raise LeaseEnded(f"lease {lease_id} ended already")
        await self._relay.relay_all(ctx.org_id, rows)
        await self._offer(ctx, ended.station_id)
        return ended

    async def _renewed(
        self,
        org_id: UUID,
        job: StationJob,
        now: datetime,
        length: timedelta,
        *,
        lapsed: bool = False,
    ) -> float | None:
        """The seconds a job's lease has left once renewed for `length` from
        now, never shortened; None when it is no longer live. With `lapsed`,
        a lease past its end that no grant took over renews too."""
        lease = await self._storage.read_lease(org_id, job.lease_id)
        if lease is None or lease.ended_at is not None:
            return None
        if lease.expires_at <= now and not lapsed:
            return None
        until = renewed_until(lease.expires_at, now, length)
        renewed = await self._storage.renew_lease(
            org_id, lease.id, job.token, now, until, lapsed=lapsed
        )
        return None if renewed is None else seconds_left(renewed.expires_at, now)

    # A validation session's station.

    async def _validation(self, ctx: TenantContext, target_id: UUID) -> ValidationSession | None:
        try:
            return await self._validations.get_validation(ctx, target_id)
        except NotFound:
            return None

    async def _validation_job(
        self, ctx: TenantContext, validation: ValidationSession
    ) -> StationJob | None:
        """A validation's run, as a job under a lease of its own: a free
        station of its lab that no session waits for in line, granted by the
        same conditional write as any grant, so it never goes ahead of a
        session in line nor beside a live lease. Its one command is its check,
        with its parameters. None when no station of its lab is free."""
        margin = self._options.skew_margin
        stations = await self._storage.read_lab_stations(
            ctx.org_id, validation.lab_id, self._options.max_stations
        )
        for station in stations:
            now = self._clock()
            if not free(station, now, margin):
                continue
            line = await self._storage.read_line(
                ctx.org_id, station.pool_id, self._options.max_line
            )
            if any(serves(station, entry) for entry in line):
                continue
            lease = StationLease(
                id=new_id(),
                created_at=now,
                updated_at=now,
                created_by=validation.created_by,
                updated_by=validation.created_by,
                station_id=station.id,
                lab_id=station.lab_id,
                pool_id=station.pool_id,
                entry_id=None,
                session_id=validation.id,
                token=station.token + 1,
                expires_at=now + self._options.job_lease,
            )
            rows = (
                outbox_row(
                    ctx,
                    LEASE_GRANTED,
                    lease.id,
                    {"station_id": str(station.id), "token": lease.token},
                ),
            )
            if not await self._storage.grant(ctx.org_id, lease, margin, rows):
                continue
            await self._relay.relay_all(ctx.org_id, rows)
            job = StationJob(
                id=validation.id,
                created_at=now,
                updated_at=now,
                created_by=validation.created_by,
                updated_by=validation.created_by,
                lease_id=lease.id,
                station_id=station.id,
                lab_id=station.lab_id,
                session_id=validation.id,
                token=lease.token,
                project=validation.check_name,
                candidate=validation.check_version,
                procedure=validation.check_name,
                procedure_version=validation.check_version,
                commands=(
                    StationCommand(
                        operation=validation.check_name, parameters=validation.parameters
                    ),
                ),
            )
            created = (outbox_row(ctx, JOB_CREATED, job.id, {"lease_id": str(lease.id)}),)
            if not await self._storage.create_job(ctx.org_id, job, created):
                # Another claim made it first: this grant goes back.
                await self._end(ctx, lease.id, LeaseEnd.RELEASED)
                return await self._storage.read_job(ctx.org_id, job.id)
            await self._relay.relay_all(ctx.org_id, created)
            return job
        return None

    # Helpers.

    async def _reused(
        self, rctx: RequestContext, org_id: UUID, lab_id: UUID, issued_by: UUID
    ) -> None:
        """A credential that rotated already, presented to rotate again or
        after its grace: two daemons hold the lab's identity, the daemon and
        a copy. Neither can be told from the other, so every credential of
        the lab's daemon is revoked, and its owner issues it a first one
        again. The person who issued the first answers for the revocation."""
        ctx = await self._tenancy.service_context(rctx, org_id, issued_by)
        rows = (outbox_row(ctx, DAEMON_REVOKED, lab_id, {"reason": "credential_reused"}),)
        await self._storage.revoke_daemon(org_id, lab_id, self._clock(), rows)
        await self._relay.relay_all(org_id, rows)
        OUTCOMES.labels(subsystem="stations", outcome="credential_reused").inc()
        log.warning("lab %s: a rotated daemon credential was presented again; revoked", lab_id)

    async def _leave_every_line(self, ctx: TenantContext, session_id: UUID) -> int:
        waiting = await self._storage.read_waiting(ctx.org_id, session_id, self._options.max_line)
        return await self._storage.leave(
            ctx.org_id, tuple(entry.id for entry in waiting), self._clock(), ctx.user_id
        )

    async def _place(self, ctx: TenantContext, entry_id: UUID) -> LinePlace:
        entry = await self._storage.read_entry(ctx.org_id, entry_id)
        if entry is None:
            raise NotFound(f"line entry {entry_id} not found")
        pool = await self._pool(ctx, entry.pool_id)
        line = await self._storage.read_line(ctx.org_id, entry.pool_id, self._options.max_line)
        stations = await self._storage.read_stations(
            ctx.org_id, entry.pool_id, self._options.max_stations
        )
        return self._placed(entry, line, stations, pool)

    @staticmethod
    def _placed(
        entry: LineEntry, line: Sequence[LineEntry], stations: Sequence[Station], pool: StationPool
    ) -> LinePlace:
        serving = sum(1 for station in stations if serves(station, entry))
        return place(entry, in_line_order(line), serving, pool.job_seconds)

    async def _running(self, daemon: DaemonIdentity, job_id: UUID) -> StationJob:
        job = await self._storage.read_job(daemon.org_id, job_id)
        if job is None or job.lab_id != daemon.lab_id:
            raise NotFound(f"station job {job_id} not found")
        if job.state is not JobState.RUNNING:
            raise JobSettled(f"station job {job_id} is {job.state.value}")
        return job

    @staticmethod
    def _job_rows(ctx: TenantContext, job: StationJob) -> tuple[OutboxRow, ...]:
        """The rows a job lands with. Its station work is one of them:
        placement reads the lab off its payload and puts it on the lab's
        lane, which only the lab's daemon claims."""
        return (
            outbox_row(ctx, JOB_CREATED, job.id, {"lease_id": str(job.lease_id)}),
            outbox_row(
                ctx,
                work_row_kind(WorkKind.STATION),
                job.id,
                StationPayload(lab_id=job.lab_id).model_dump(mode="json"),
            ),
        )

    @staticmethod
    def _carried(entry: LineEntry, lease: StationLease) -> StationJob:
        """The job an entry carries, sent under the lease its grant gives:
        on the word of who asked, under the entry's id, bound to what the
        ask binds, at the lease's token."""
        return StationJob(
            id=entry.id,
            created_at=lease.created_at,
            updated_at=lease.created_at,
            created_by=entry.created_by,
            updated_by=entry.created_by,
            lease_id=lease.id,
            station_id=lease.station_id,
            lab_id=lease.lab_id,
            session_id=entry.session_id,
            token=lease.token,
            project=entry.project,
            candidate=entry.candidate,
            procedure=entry.procedure,
            procedure_version=entry.procedure_version,
            commands=entry.commands,
        )

    @staticmethod
    def _claimed(job: StationJob) -> WorkItem:
        assert job.claim is not None  # a running job holds its claim
        return WorkItem.model_validate(job.claim)

    @staticmethod
    def _record(job: StationJob, report: JobReport, now: datetime) -> ExecutionRecord:
        """The run of a job as the execution record every run is: what the
        job ran on, from the store, and what came of it, from the daemon."""
        return ExecutionRecord(
            id=report.run_id,
            created_at=now,
            session_id=job.session_id,
            project=job.project,
            purpose=RunPurpose.WORK,
            version=job.candidate,
            dirty=False,
            environment=Environment(image=report.daemon_version),
            host=f"lab:{job.lab_id}",
            isolation="station",
            executor=f"daemon:{job.lab_id}",
            check=job.procedure,
            check_version=job.procedure_version,
            parameters={
                "station_id": str(job.station_id),
                "token": job.token,
                "commands": [command.model_dump(mode="json") for command in job.commands],
            },
            metrics={
                "commands_run": report.commands_run,
                "refused": [refusal.model_dump(mode="json") for refusal in report.refused],
            },
            started_at=report.started_at,
            finished_at=report.finished_at,
            outcome=report.outcome,
            cases=report.cases,
            dependencies=(Dependency(name=report.adapter, provenance=report.provenance),),
            abort=report.abort,
        )

    async def _lab(self, ctx: TenantContext, lab_id: UUID) -> Lab:
        lab = await self._storage.read_lab(ctx.org_id, lab_id)
        if lab is None:
            raise NotFound(f"lab {lab_id} not found")
        return lab

    async def _pool(self, ctx: TenantContext, pool_id: UUID) -> StationPool:
        pool = await self._storage.read_pool(ctx.org_id, pool_id)
        if pool is None:
            raise NotFound(f"station pool {pool_id} not found")
        return pool

    async def _station(self, ctx: TenantContext, station_id: UUID) -> Station:
        station = await self._storage.read_station(ctx.org_id, station_id)
        if station is None:
            raise NotFound(f"station {station_id} not found")
        return station

    def _stamped[T: Lab | StationPool | Station](self, ctx: TenantContext, entity: T) -> T:
        now = self._clock()
        return entity.model_copy(
            update={
                "created_at": now,
                "updated_at": now,
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
            }
        )

    def _credential(
        self, lab_id: UUID, issued_by: UUID, now: datetime, ttl: timedelta
    ) -> tuple[str, DaemonCredential]:
        secret, digest = mint()
        credential = DaemonCredential(
            id=new_id(),
            created_at=now,
            lab_id=lab_id,
            issued_by=issued_by,
            digest=digest,
            expires_at=now + ttl,
        )
        return secret, credential

    @staticmethod
    def _issued(secret: str, credential: DaemonCredential) -> IssuedDaemonCredential:
        return IssuedDaemonCredential(
            credential=secret,
            credential_id=credential.id,
            lab_id=credential.lab_id,
            expires_at=credential.expires_at,
        )
