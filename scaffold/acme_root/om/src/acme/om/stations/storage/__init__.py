"""Storage of the stations swimlane: a tenant's labs, station pools, and
stations; its daemons' credentials; the line; the leases; and the jobs
sent under them. Every operation takes org_id first, except the lookup by
a daemon credential's digest, which finds the tenant. A grant is one
conditional write on the station's row, with the lease and the entry it
settles, in one commit."""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from uuid import UUID

from acme.om.outbox.types.row import OutboxRow
from acme.om.stations.types.daemon import DaemonCredential
from acme.om.stations.types.job import JobState, StationJob
from acme.om.stations.types.lease import LeaseEnd, StationLease
from acme.om.stations.types.line import LineEntry
from acme.om.stations.types.station import Lab, Station, StationPool


class StationsStorageInterface(ABC):
    # Labs, pools, and stations.

    @abstractmethod
    async def create_lab(self, org_id: UUID, lab: Lab, outbox_rows: tuple[OutboxRow, ...]) -> bool:
        """The create; False, with nothing landed, when the id is written."""
        ...

    @abstractmethod
    async def read_lab(self, org_id: UUID, lab_id: UUID) -> Lab | None: ...

    @abstractmethod
    async def create_pool(
        self, org_id: UUID, pool: StationPool, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create; False, with nothing landed, when the id is written."""
        ...

    @abstractmethod
    async def read_pool(self, org_id: UUID, pool_id: UUID) -> StationPool | None: ...

    @abstractmethod
    async def create_station(
        self, org_id: UUID, station: Station, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create; False, with nothing landed, when the id is written."""
        ...

    @abstractmethod
    async def read_station(self, org_id: UUID, station_id: UUID) -> Station | None: ...

    @abstractmethod
    async def read_stations(self, org_id: UUID, pool_id: UUID, limit: int) -> list[Station]:
        """The pool's stations in id order, at most `limit`."""
        ...

    # A lab's daemon.

    @abstractmethod
    async def create_daemon_credential(
        self, org_id: UUID, credential: DaemonCredential, outbox_rows: tuple[OutboxRow, ...]
    ) -> None: ...

    @abstractmethod
    async def read_daemon_credential_by_digest(
        self, digest: str
    ) -> tuple[UUID, DaemonCredential] | None:
        """Cross-tenant: a daemon's call names no tenant, so its credential's
        digest finds the tenant with the credential, ended ones included."""
        ...

    @abstractmethod
    async def rotate_daemon_credential(
        self, org_id: UUID, retiring_id: UUID, retire_at: datetime, minted: DaemonCredential
    ) -> bool:
        """In one commit: the retiring credential ends at `retire_at`, when
        that is sooner than its end, and `minted` lands. False, with nothing
        landed, when the tenant holds no live retiring credential of that
        lab."""
        ...

    @abstractmethod
    async def end_daemon_credentials(
        self, org_id: UUID, lab_id: UUID, at: datetime, outbox_rows: tuple[OutboxRow, ...]
    ) -> int:
        """Ends every live credential of the lab's daemon at `at`; returns how
        many."""
        ...

    # The line.

    @abstractmethod
    async def create_entry(
        self, org_id: UUID, entry: LineEntry, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create; False, with nothing landed, when the id is written."""
        ...

    @abstractmethod
    async def read_entry(self, org_id: UUID, entry_id: UUID) -> LineEntry | None: ...

    @abstractmethod
    async def read_line(self, org_id: UUID, pool_id: UUID, limit: int) -> list[LineEntry]:
        """The pool's waiting entries, its stations' lines among them, in
        line order (`rules.in_line_order`), at most `limit`."""
        ...

    @abstractmethod
    async def read_waiting(self, org_id: UUID, session_id: UUID, limit: int) -> list[LineEntry]:
        """The session's waiting entries, in every line, at most `limit`."""
        ...

    @abstractmethod
    async def write_rank(
        self, org_id: UUID, entry_id: UUID, rank: float, at: datetime, by: UUID
    ) -> bool:
        """Moves a waiting entry to `rank`; False when the tenant holds no such
        waiting entry."""
        ...

    @abstractmethod
    async def leave(self, org_id: UUID, entry_ids: tuple[UUID, ...], at: datetime, by: UUID) -> int:
        """Every named entry still waiting leaves its line at `at`; returns how
        many did."""
        ...

    # The leases.

    @abstractmethod
    async def grant(
        self,
        org_id: UUID,
        lease: StationLease,
        margin: timedelta,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> bool:
        """The grant, in one commit, or nothing. The station's row takes the
        lease and its token by a conditional write that fails while a live
        lease holds it: one ended, or past its end by more than `margin` at
        `lease.created_at`, does not. The token is one above the station's,
        and `lease.token` must say so. The entry the lease settles goes from
        waiting to granted by a write conditional on its waiting, the lease
        the station held before ends as expired, and `lease` lands. False,
        with nothing landed, when the station is held, its token moved, or
        the entry no longer waits."""
        ...

    @abstractmethod
    async def read_lease(self, org_id: UUID, lease_id: UUID) -> StationLease | None: ...

    @abstractmethod
    async def renew_lease(
        self, org_id: UUID, lease_id: UUID, token: int, now: datetime, until: datetime
    ) -> StationLease | None:
        """The lease, and the station's hold with it, last until `until`: a
        write conditional on the lease being live at `now` and the station
        held by it at `token`. None, with nothing written, otherwise."""
        ...

    @abstractmethod
    async def end_lease(
        self,
        org_id: UUID,
        lease_id: UUID,
        at: datetime,
        end: LeaseEnd,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> StationLease | None:
        """Ends a live lease at `at` and frees the station it holds, in one
        commit. None, with nothing written, when the lease is ended already
        or the tenant holds no such lease."""
        ...

    # The jobs.

    @abstractmethod
    async def create_job(
        self, org_id: UUID, job: StationJob, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create, with its outbox rows, the one that asks for its station
        work among them, in one commit; False, with nothing landed, when the
        id is written."""
        ...

    @abstractmethod
    async def read_job(self, org_id: UUID, job_id: UUID) -> StationJob | None: ...

    @abstractmethod
    async def write_job(
        self,
        org_id: UUID,
        job: StationJob,
        expected: JobState,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> bool:
        """Lands the job over the one stored in state `expected`; False, with
        nothing landed, when the stored one is in another."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of each table of a deleted tenant past its
        retention; returns how many went."""
        ...
