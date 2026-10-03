from datetime import datetime, timedelta
from uuid import UUID

from acme.om.exceptions import UniqueKeyTaken
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.stations.rules import free, in_line_order
from acme.om.stations.storage import StationsStorageInterface
from acme.om.stations.types.daemon import DaemonCredential, Rotation
from acme.om.stations.types.job import JobState, StationJob
from acme.om.stations.types.lease import LeaseEnd, StationLease
from acme.om.stations.types.line import EntryState, LineEntry
from acme.om.stations.types.station import Lab, Station, StationPool
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class StationsStorageMemoryImpl(MemoryStorageBase, StationsStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._labs: MemoryTable[Lab] = {}
        self._pools: MemoryTable[StationPool] = {}
        self._stations: MemoryTable[Station] = {}
        self._credentials: MemoryTable[DaemonCredential] = {}
        self._entries: MemoryTable[LineEntry] = {}
        self._leases: MemoryTable[StationLease] = {}
        self._jobs: MemoryTable[StationJob] = {}

    # Labs, pools, and stations.

    async def create_lab(self, org_id: UUID, lab: Lab, outbox_rows: tuple[OutboxRow, ...]) -> bool:
        async with self._lock:
            return self._insert(self._labs, org_id, lab, outbox_rows)

    async def read_lab(self, org_id: UUID, lab_id: UUID) -> Lab | None:
        return self._get(self._labs, org_id, lab_id)

    async def create_pool(
        self, org_id: UUID, pool: StationPool, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            return self._insert(self._pools, org_id, pool, outbox_rows)

    async def read_pool(self, org_id: UUID, pool_id: UUID) -> StationPool | None:
        return self._get(self._pools, org_id, pool_id)

    async def create_station(
        self, org_id: UUID, station: Station, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            return self._insert(self._stations, org_id, station, outbox_rows)

    async def read_station(self, org_id: UUID, station_id: UUID) -> Station | None:
        return self._get(self._stations, org_id, station_id)

    async def read_stations(self, org_id: UUID, pool_id: UUID, limit: int) -> list[Station]:
        found = [s for s in self._rows(self._stations, org_id) if s.pool_id == pool_id]
        return found[:limit]

    async def read_lab_stations(self, org_id: UUID, lab_id: UUID, limit: int) -> list[Station]:
        found = [s for s in self._rows(self._stations, org_id) if s.lab_id == lab_id]
        return found[:limit]

    # A lab's daemon.

    async def create_daemon_credential(
        self, org_id: UUID, credential: DaemonCredential, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        async with self._lock:
            self._unique(credential)
            self._insert(self._credentials, org_id, credential, outbox_rows)

    async def read_daemon_credential_by_digest(
        self, digest: str
    ) -> tuple[UUID, DaemonCredential] | None:
        for org_id, credential in self._rows_across_tenants(self._credentials):
            if credential.digest == digest:
                return org_id, credential
        return None

    async def rotate_daemon_credential(
        self,
        org_id: UUID,
        retiring_id: UUID,
        at: datetime,
        retire_at: datetime,
        minted: DaemonCredential,
    ) -> Rotation:
        async with self._lock:
            retiring = self._get(self._credentials, org_id, retiring_id)
            if (
                retiring is None
                or retiring.lab_id != minted.lab_id
                or self._get(self._labs, org_id, minted.lab_id) is None
            ):
                return Rotation.MISSING
            if retiring.revoked_at is not None:
                return Rotation.REVOKED
            if retiring.rotated_at is not None:
                return Rotation.REUSED
            self._unique(minted)
            ends = min(retiring.expires_at, retire_at)
            self._put(
                self._credentials,
                org_id,
                retiring.model_copy(update={"rotated_at": at, "expires_at": ends}),
            )
            self._insert(self._credentials, org_id, minted)
            return Rotation.ROTATED

    async def revoke_daemon(
        self, org_id: UUID, lab_id: UUID, at: datetime, outbox_rows: tuple[OutboxRow, ...]
    ) -> int:
        async with self._lock:
            live = 0
            for credential in self._rows(self._credentials, org_id):
                if credential.lab_id != lab_id or credential.revoked_at is not None:
                    continue
                live += credential.expires_at > at
                self._put(
                    self._credentials,
                    org_id,
                    credential.model_copy(
                        update={"revoked_at": at, "expires_at": min(credential.expires_at, at)}
                    ),
                )
            self._land(org_id, outbox_rows)
            return live

    def _unique(self, credential: DaemonCredential) -> None:
        if credential.id in self._credentials or any(
            held.digest == credential.digest for held in self._every(self._credentials)
        ):
            raise UniqueKeyTaken(f"daemon_credentials {credential.id}: the id or digest is taken")

    # The line.

    async def create_entry(
        self, org_id: UUID, entry: LineEntry, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            return self._insert(self._entries, org_id, entry, outbox_rows)

    async def read_entry(self, org_id: UUID, entry_id: UUID) -> LineEntry | None:
        return self._get(self._entries, org_id, entry_id)

    async def read_line(self, org_id: UUID, pool_id: UUID, limit: int) -> list[LineEntry]:
        waiting = (
            entry
            for entry in self._rows(self._entries, org_id)
            if entry.pool_id == pool_id and entry.state is EntryState.WAITING
        )
        return in_line_order(waiting)[:limit]

    async def read_waiting(self, org_id: UUID, session_id: UUID, limit: int) -> list[LineEntry]:
        found = [
            entry
            for entry in self._rows(self._entries, org_id)
            if entry.session_id == session_id and entry.state is EntryState.WAITING
        ]
        return found[:limit]

    async def write_rank(
        self, org_id: UUID, entry_id: UUID, rank: float, at: datetime, by: UUID
    ) -> bool:
        async with self._lock:
            entry = self._get(self._entries, org_id, entry_id)
            if entry is None or entry.state is not EntryState.WAITING:
                return False
            moved = entry.model_copy(update={"rank": rank, "updated_at": at, "updated_by": by})
            self._put(self._entries, org_id, moved)
            return True

    async def leave(self, org_id: UUID, entry_ids: tuple[UUID, ...], at: datetime, by: UUID) -> int:
        async with self._lock:
            left = 0
            for entry_id in entry_ids:
                entry = self._get(self._entries, org_id, entry_id)
                if entry is None or entry.state is not EntryState.WAITING:
                    continue
                gone = entry.model_copy(
                    update={
                        "state": EntryState.LEFT,
                        "settled_at": at,
                        "updated_at": at,
                        "updated_by": by,
                    }
                )
                self._put(self._entries, org_id, gone)
                left += 1
            return left

    # The leases.

    async def grant(
        self,
        org_id: UUID,
        lease: StationLease,
        margin: timedelta,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> bool:
        async with self._lock:
            now = lease.created_at
            station = self._get(self._stations, org_id, lease.station_id)
            entry = (
                None if lease.entry_id is None else self._get(self._entries, org_id, lease.entry_id)
            )
            if station is None or lease.id in self._leases:
                return False
            if not free(station, now, margin) or station.token != lease.token - 1:
                return False
            if lease.entry_id is not None and (
                entry is None or entry.state is not EntryState.WAITING
            ):
                return False
            for held in self._rows(self._leases, org_id):
                if held.station_id == station.id and held.ended_at is None:
                    expired = held.model_copy(
                        update={"ended_at": now, "ended": LeaseEnd.EXPIRED, "updated_at": now}
                    )
                    self._put(self._leases, org_id, expired)
            self._put(
                self._stations,
                org_id,
                station.model_copy(
                    update={
                        "token": lease.token,
                        "lease_id": lease.id,
                        "held_until": lease.expires_at,
                        "updated_at": now,
                    }
                ),
            )
            if entry is not None:
                self._put(
                    self._entries,
                    org_id,
                    entry.model_copy(
                        update={
                            "state": EntryState.GRANTED,
                            "lease_id": lease.id,
                            "settled_at": now,
                            "updated_at": now,
                            "updated_by": lease.created_by,
                        }
                    ),
                )
            self._insert(self._leases, org_id, lease, outbox_rows)
            return True

    async def read_lease(self, org_id: UUID, lease_id: UUID) -> StationLease | None:
        return self._get(self._leases, org_id, lease_id)

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
        async with self._lock:
            lease = self._get(self._leases, org_id, lease_id)
            if lease is None or lease.ended_at is not None:
                return None
            if lease.expires_at <= now and not lapsed:
                return None
            station = self._get(self._stations, org_id, lease.station_id)
            if station is None or station.lease_id != lease_id or station.token != token:
                return None
            renewed = lease.model_copy(update={"expires_at": until, "updated_at": now})
            self._put(self._leases, org_id, renewed)
            self._put(
                self._stations,
                org_id,
                station.model_copy(update={"held_until": until, "updated_at": now}),
            )
            return renewed

    async def end_lease(
        self,
        org_id: UUID,
        lease_id: UUID,
        at: datetime,
        end: LeaseEnd,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> StationLease | None:
        async with self._lock:
            lease = self._get(self._leases, org_id, lease_id)
            if lease is None or lease.ended_at is not None:
                return None
            ended = lease.model_copy(update={"ended_at": at, "ended": end, "updated_at": at})
            self._put(self._leases, org_id, ended, outbox_rows)
            station = self._get(self._stations, org_id, lease.station_id)
            if station is not None and station.lease_id == lease_id:
                freed = station.model_copy(
                    update={"lease_id": None, "held_until": None, "updated_at": at}
                )
                self._put(self._stations, org_id, freed)
            return ended

    # The jobs.

    async def create_job(
        self, org_id: UUID, job: StationJob, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            return self._insert(self._jobs, org_id, job, outbox_rows)

    async def read_job(self, org_id: UUID, job_id: UUID) -> StationJob | None:
        return self._get(self._jobs, org_id, job_id)

    async def write_job(
        self,
        org_id: UUID,
        job: StationJob,
        expected: JobState,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> bool:
        async with self._lock:
            stored = self._get(self._jobs, org_id, job.id)
            if stored is None or stored.state is not expected:
                return False
            self._put(self._jobs, org_id, job, outbox_rows)
            return True

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            purged = 0
            for table in (
                self._jobs,
                self._leases,
                self._entries,
                self._credentials,
                self._stations,
                self._pools,
                self._labs,
            ):
                gone = [
                    entity_id for entity_id, (row_org, _) in table.items() if row_org == org_id
                ][:limit]
                for entity_id in gone:
                    del table[entity_id]
                purged += len(gone)
            return purged
