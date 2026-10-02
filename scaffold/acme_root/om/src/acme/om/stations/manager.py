"""The stations swimlane: a tenant's labs, pools, and stations; the line a
session waits in, parked, for a scarce station; the lease a grant gives,
fenced by a token that grows with every grant; the jobs sent under it; and
the calls of a lab's daemon, a least-privilege client of the gateway that
pulls its lab's station work, renews the lease of the job it runs, and
reports the run. A station's limits are not here: they are its owner's,
on its host, and nothing here can raise them (ADR 2006)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from acme.om.context import RequestContext, TenantContext
from acme.om.stations.types.daemon import DaemonIdentity, IssuedDaemonCredential
from acme.om.stations.types.job import ClaimedJob, JobReport, StationCommand, StationJob
from acme.om.stations.types.lease import LeaseTime, StationLease
from acme.om.stations.types.line import LinePlace, StationAsk
from acme.om.stations.types.station import Lab, Station, StationPool


class StationsManagerInterface(ABC):
    # A tenant's side: what its stations are, who may reach them, and the
    # line.

    @abstractmethod
    async def create_lab(self, ctx: TenantContext, lab: Lab) -> Lab:
        """A lab under the caller's tenant, its provenance stamped from the
        context. A retry under the same id answers the row as stored.
        Requires the members permission: a person who manages the
        stations."""
        ...

    @abstractmethod
    async def create_pool(self, ctx: TenantContext, pool: StationPool) -> StationPool:
        """A pool of stations of one kind; as `create_lab`."""
        ...

    @abstractmethod
    async def add_station(self, ctx: TenantContext, station: Station) -> Station:
        """A station of one of the tenant's labs, in one of its pools; as
        `create_lab`. Its token, its lease, and its hold are the manager's,
        whatever the caller sets. NotFound when the tenant holds no such lab
        or pool."""
        ...

    @abstractmethod
    async def get_stations(self, ctx: TenantContext, pool_id: UUID) -> tuple[Station, ...]:
        """The pool's stations, each with the lease that holds it. NotFound
        when the tenant holds no such pool."""
        ...

    @abstractmethod
    async def issue_daemon_credential(
        self, ctx: TenantContext, lab_id: UUID
    ) -> IssuedDaemonCredential:
        """The lab daemon's first credential, in the clear once, of a kind and
        a prefix of its own: it lives a day, for its owner to install it, and
        the daemon rotates it from then on. Only its digest is kept. Requires
        the members permission. NotFound when the tenant holds no such lab."""
        ...

    @abstractmethod
    async def revoke_daemon(self, ctx: TenantContext, lab_id: UUID) -> int:
        """Ends every credential of the lab's daemon at once: its next call is
        refused. Returns how many ended. Requires the members permission."""
        ...

    @abstractmethod
    async def join(self, ctx: TenantContext, entry_id: UUID, ask: StationAsk) -> LinePlace:
        """The session joins the line of the station it names, or of its pool,
        under `entry_id`, bound to what the ask binds, and is told its place.
        A free station that serves the line is granted at once, to the first
        in line that waits. A session waits once it is parked on the line
        (`rules.LINE_PARK`); one that has not parked yet keeps its place and
        is passed over. Requires the write permission. NotFound when the
        tenant holds no such session, pool, or station; ValidationFailed when
        the station is of another pool. A retry under the same id answers
        the entry's place."""
        ...

    @abstractmethod
    async def get_line(self, ctx: TenantContext, pool_id: UUID) -> tuple[LinePlace, ...]:
        """The pool's line, its stations' lines in it, each waiting entry with
        its place, in the order it is served."""
        ...

    @abstractmethod
    async def reorder(self, ctx: TenantContext, entry_id: UUID, before: UUID | None) -> LinePlace:
        """A person who manages the stations moves a waiting entry ahead of
        `before`, a waiting entry of the same pool, or to the end of the line
        with None. Requires the members permission. NotFound when the tenant
        holds no such waiting entry."""
        ...

    @abstractmethod
    async def leave(self, ctx: TenantContext, session_id: UUID) -> int:
        """The session leaves every line it stands in, as it does when it
        finishes or is cancelled. Returns how many places it left. Requires
        the write permission."""
        ...

    @abstractmethod
    async def release_lease(self, ctx: TenantContext, lease_id: UUID) -> StationLease:
        """The holding session lets its lease go: the lease ends, and the
        station goes to the first in line that waits. Requires the write
        permission. LeaseEnded when it ended already."""
        ...

    @abstractmethod
    async def revoke_lease(self, ctx: TenantContext, lease_id: UUID) -> StationLease:
        """A person who manages the stations ends a lease. The holding session
        is told by an event, the daemon refuses the lease's next renewal and
        takes the station's controlled stop, and the station goes to the
        first in line that waits. Requires the members permission."""
        ...

    @abstractmethod
    async def submit_job(
        self,
        ctx: TenantContext,
        job_id: UUID,
        lease_id: UUID,
        commands: Sequence[StationCommand],
    ) -> StationJob:
        """A job under a live lease, and its station work on its lab's lane,
        in one write. The station, the token, and what the job may run are
        the lease's, never the caller's. Requires the write permission.
        LeaseEnded when the lease is no longer live. A retry under the same
        id answers the job as stored."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep's purge of a tenant deleted past its retention: its labs,
        pools, stations, credentials, line, leases, and jobs go; any other
        tenant costs nothing."""
        ...

    # A daemon's side: the transitions its calls make from the request
    # stage. A daemon is no person, so none of them builds a tenant stage of
    # its own.

    @abstractmethod
    async def authenticate(self, rctx: RequestContext, credential: str) -> DaemonIdentity:
        """Platform-internal: the lab daemon behind a daemon credential.
        Refuses any other kind of credential, and an ended one."""
        ...

    @abstractmethod
    async def rotate(self, rctx: RequestContext, daemon: DaemonIdentity) -> IssuedDaemonCredential:
        """Platform-internal: the daemon's next credential, in the clear once.
        The one it called with ends after a short grace."""
        ...

    @abstractmethod
    async def claim(
        self, rctx: RequestContext, daemon: DaemonIdentity, station_version: int
    ) -> ClaimedJob | None:
        """Platform-internal: the next item of the daemon's lab, claimed by
        placement from the lab's lane alone, read off its identity. Refused,
        before any claim, when the version of `station` work it reads is
        below the floor. A job's lease is renewed for its run, and the answer
        says how long it has left. A validation session's item becomes a job
        under a lease of its own, on a free station of its lab that no
        session waits for; with none free, it waits on its lane. A job
        claimed again after it ran is failed for good, never run twice. None
        when nothing is ready."""
        ...

    @abstractmethod
    async def renew(self, rctx: RequestContext, daemon: DaemonIdentity, job_id: UUID) -> LeaseTime:
        """Platform-internal: the daemon renews, as the executor, the lease of
        a job of its lab that it runs, and the job's claim with it. LeaseEnded
        when the lease ran out or was revoked or released: the daemon stops
        the station. The daemon renews only what a grant gave."""
        ...

    @abstractmethod
    async def report(
        self, rctx: RequestContext, daemon: DaemonIdentity, job_id: UUID, report: JobReport
    ) -> StationJob:
        """Platform-internal: the run of a job of the daemon's lab is recorded
        as an execution record, every refused command in it, the job is
        finished, and its claim settled. Its lease goes back to the hold
        time its parked session has; a validation session's run finishes
        that session instead, and its lease ends. A report again with the
        same run answers the job as stored; with another, JobSettled."""
        ...
