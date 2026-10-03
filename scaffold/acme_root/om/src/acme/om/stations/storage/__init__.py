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
from acme.om.stations.types.daemon import DaemonCredential, Rotation
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

    @abstractmethod
    async def read_lab_stations(self, org_id: UUID, lab_id: UUID, limit: int) -> list[Station]:
        """The lab's stations in id order, at most `limit`."""
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
        self,
        org_id: UUID,
        retiring_id: UUID,
        at: datetime,
        retire_at: datetime,
        minted: DaemonCredential,
    ) -> Rotation:
        """A credential rotates once, under the lab's row lock, which a
        revocation takes too. In one commit: the retiring credential is
        marked rotated at `at` and ends at `retire_at` when that is sooner,
        and `minted` lands. `REVOKED`, with nothing landed, when the
        retiring credential is revoked; `REUSED` when it rotated already;
        `MISSING` when the tenant holds no such credential of that lab, or
        no such lab."""
        ...

    @abstractmethod
    async def revoke_daemon(
        self, org_id: UUID, lab_id: UUID, at: datetime, outbox_rows: tuple[OutboxRow, ...]
    ) -> int:
        """Marks every credential of the lab's daemon not yet revoked as
        revoked at `at`, and ends it then, under the lab's row lock, so a
        rotation either lands before and its credential is revoked with
        the rest, or reads the mark and lands nothing. Returns how many of
        them were live at `at`."""
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
        job: StationJob | None = None,
    ) -> bool:
        """The grant, in one commit, or nothing. The station's row takes the
        lease and its token by a conditional write that fails while a live
        lease holds it: one ended, or past its end by more than `margin` at
        `lease.created_at`, does not. The token is one above the station's,
        and `lease.token` must say so. The entry the lease settles, when it
        names one, goes from waiting to granted by a write conditional on its
        waiting, the lease the station held before ends as expired, and
        `lease` lands, with `job`, the job its entry carries, when it carries
        one. False, with nothing landed, when the station is held, its token
        moved, or the entry no longer waits."""
        ...

    @abstractmethod
    async def read_lease(self, org_id: UUID, lease_id: UUID) -> StationLease | None: ...

    @abstractmethod
    async def renew_lease(
        self,
        org_id: UUID,
        lease_id: UUID,
        token: int,
        now: datetime,
        until: datetime,
        *,
        lapsed: bool = False,
    ) -> StationLease | None:
        """The lease, and the station's hold with it, last until `until`: a
        write conditional on the lease being live at `now` and the station
        held by it at `token`. None, with nothing written, otherwise. With
        `lapsed`, a lease past its end renews too, so long as it was never
        ended and no grant took its station since: the station's row still
        names it at `token`."""
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
