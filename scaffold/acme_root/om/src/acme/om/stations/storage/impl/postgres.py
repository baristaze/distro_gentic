from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from acme.om.base import EMPTY_UUID
from acme.om.exceptions import UniqueKeyTaken
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.stations.storage import StationsStorageInterface
from acme.om.stations.storage.tables.daemon_credentials import DaemonCredentials
from acme.om.stations.storage.tables.labs import Labs
from acme.om.stations.storage.tables.station_jobs import StationJobs
from acme.om.stations.storage.tables.station_leases import StationLeases
from acme.om.stations.storage.tables.station_line_entries import StationLineEntries
from acme.om.stations.storage.tables.station_pools import StationPools
from acme.om.stations.storage.tables.stations import Stations
from acme.om.stations.types.daemon import DaemonCredential, Rotation
from acme.om.stations.types.job import JobState, StationJob
from acme.om.stations.types.lease import LeaseEnd, StationLease
from acme.om.stations.types.line import EntryState, LineEntry
from acme.om.stations.types.station import Lab, Station, StationPool
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted, violated_constraint
from acme.om.storage.utils.translation import to_model, to_row, to_values

PURGED_IN_ORDER = (
    StationJobs,
    StationLeases,
    StationLineEntries,
    DaemonCredentials,
    Stations,
    StationPools,
    Labs,
)
"""A deleted tenant's tables, each purged a batch at a time."""

WAITING = EntryState.WAITING.value


class StationsStoragePostgresImpl(PgStorageBase, StationsStorageInterface):
    # Labs, pools, and stations.

    async def create_lab(self, org_id: UUID, lab: Lab, outbox_rows: tuple[OutboxRow, ...]) -> bool:
        return await self._insert(Labs, org_id, lab, outbox_rows)

    async def read_lab(self, org_id: UUID, lab_id: UUID) -> Lab | None:
        stmt = select(Labs).where(Labs.org_id == org_id, Labs.id == lab_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Lab)

    async def create_pool(
        self, org_id: UUID, pool: StationPool, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(StationPools, org_id, pool, outbox_rows)

    async def read_pool(self, org_id: UUID, pool_id: UUID) -> StationPool | None:
        stmt = select(StationPools).where(StationPools.org_id == org_id, StationPools.id == pool_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, StationPool)

    async def create_station(
        self, org_id: UUID, station: Station, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(Stations, org_id, station, outbox_rows)

    async def read_station(self, org_id: UUID, station_id: UUID) -> Station | None:
        stmt = select(Stations).where(Stations.org_id == org_id, Stations.id == station_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Station)

    async def read_lab_stations(self, org_id: UUID, lab_id: UUID, limit: int) -> list[Station]:
        stmt = (
            select(Stations)
            .where(Stations.org_id == org_id, Stations.lab_id == lab_id)
            .order_by(Stations.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, Station) for row in rows]

    async def read_stations(self, org_id: UUID, pool_id: UUID, limit: int) -> list[Station]:
        stmt = (
            select(Stations)
            .where(Stations.org_id == org_id, Stations.pool_id == pool_id)
            .order_by(Stations.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, Station) for row in rows]

    # A lab's daemon.

    async def create_daemon_credential(
        self, org_id: UUID, credential: DaemonCredential, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        if not await self._insert(DaemonCredentials, org_id, credential, outbox_rows):
            raise UniqueKeyTaken(f"daemon_credentials {credential.id}: the id is taken")

    async def read_daemon_credential_by_digest(
        self, digest: str
    ) -> tuple[UUID, DaemonCredential] | None:
        stmt = select(DaemonCredentials).where(DaemonCredentials.digest == digest)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else (row.org_id, to_model(row, DaemonCredential))

    async def rotate_daemon_credential(
        self,
        org_id: UUID,
        retiring_id: UUID,
        at: datetime,
        retire_at: datetime,
        minted: DaemonCredential,
    ) -> Rotation:
        # The lab's row lock is the one a revocation takes: of a rotation and
        # a revocation at the same moment, the second reads what the first
        # wrote. The credential's own lock makes a rotation once.
        lab = (
            select(Labs.id)
            .where(Labs.org_id == org_id, Labs.id == minted.lab_id)
            .with_for_update()
        )
        held = (
            select(DaemonCredentials)
            .where(
                DaemonCredentials.org_id == org_id,
                DaemonCredentials.id == retiring_id,
                DaemonCredentials.lab_id == minted.lab_id,
            )
            .with_for_update()
        )
        async with self._session_for(held, org_id=org_id) as session:
            if (await session.execute(lab)).scalar_one_or_none() is None:
                await session.rollback()
                return Rotation.MISSING
            retiring = (await session.execute(held)).scalar_one_or_none()
            if retiring is None:
                await session.rollback()
                return Rotation.MISSING
            if retiring.revoked_at is not None:
                await session.rollback()
                return Rotation.REVOKED
            if retiring.rotated_at is not None:
                await session.rollback()
                return Rotation.REUSED
            retiring.rotated_at = at
            retiring.expires_at = min(retiring.expires_at, retire_at)
            session.add(to_row(minted, DaemonCredentials, org_id=org_id))
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise UniqueKeyTaken(
                    f"daemon_credentials {minted.id}: "
                    f"{violated_constraint(error) or 'a unique key'} is taken"
                ) from error
            return Rotation.ROTATED

    async def revoke_daemon(
        self, org_id: UUID, lab_id: UUID, at: datetime, outbox_rows: tuple[OutboxRow, ...]
    ) -> int:
        lab = select(Labs.id).where(Labs.org_id == org_id, Labs.id == lab_id).with_for_update()
        unrevoked = (
            DaemonCredentials.org_id == org_id,
            DaemonCredentials.lab_id == lab_id,
            DaemonCredentials.revoked_at.is_(None),
        )
        live = (
            select(func.count())
            .select_from(DaemonCredentials)
            .where(*unrevoked, DaemonCredentials.expires_at > at)
        )
        mark = (
            update(DaemonCredentials)
            .where(*unrevoked)
            .values(revoked_at=at, expires_at=func.least(DaemonCredentials.expires_at, at))
        )
        async with self._session_for(mark, org_id=org_id) as session:
            # Each statement after the lock reads what a rotation that held
            # it before committed, its new credential included.
            await session.execute(lab)
            ended = (await session.execute(live)).scalar_one()
            await session.execute(mark)
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()
            return ended

    # The line.

    async def create_entry(
        self, org_id: UUID, entry: LineEntry, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(StationLineEntries, org_id, entry, outbox_rows)

    async def read_entry(self, org_id: UUID, entry_id: UUID) -> LineEntry | None:
        stmt = select(StationLineEntries).where(
            StationLineEntries.org_id == org_id, StationLineEntries.id == entry_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, LineEntry)

    async def read_line(self, org_id: UUID, pool_id: UUID, limit: int) -> list[LineEntry]:
        stmt = (
            select(StationLineEntries)
            .where(
                StationLineEntries.org_id == org_id,
                StationLineEntries.pool_id == pool_id,
                StationLineEntries.state == WAITING,
            )
            .order_by(StationLineEntries.rank, StationLineEntries.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, LineEntry) for row in rows]

    async def read_waiting(self, org_id: UUID, session_id: UUID, limit: int) -> list[LineEntry]:
        stmt = (
            select(StationLineEntries)
            .where(
                StationLineEntries.org_id == org_id,
                StationLineEntries.session_id == session_id,
                StationLineEntries.state == WAITING,
            )
            .order_by(StationLineEntries.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, LineEntry) for row in rows]

    async def write_rank(
        self, org_id: UUID, entry_id: UUID, rank: float, at: datetime, by: UUID
    ) -> bool:
        stmt = (
            update(StationLineEntries)
            .where(
                StationLineEntries.org_id == org_id,
                StationLineEntries.id == entry_id,
                StationLineEntries.state == WAITING,
            )
            .values(rank=rank, updated_at=at, updated_by=by)
            .returning(StationLineEntries.id)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            moved = (await session.execute(stmt)).scalar_one_or_none() is not None
            await session.commit()
            return moved

    async def leave(self, org_id: UUID, entry_ids: tuple[UUID, ...], at: datetime, by: UUID) -> int:
        if not entry_ids:
            return 0
        stmt = (
            update(StationLineEntries)
            .where(
                StationLineEntries.org_id == org_id,
                StationLineEntries.id.in_(entry_ids),
                StationLineEntries.state == WAITING,
            )
            .values(state=EntryState.LEFT.value, settled_at=at, updated_at=at, updated_by=by)
            .returning(StationLineEntries.id)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            left = len((await session.execute(stmt)).scalars().all())
            await session.commit()
            return left

    # The leases.

    async def grant(
        self,
        org_id: UUID,
        lease: StationLease,
        margin: timedelta,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> bool:
        now = lease.created_at
        # The condition is the write's own: a station a live lease holds, or
        # whose token moved since it was read, takes nothing. A grant that
        # races this one waits on the row and finds the condition false.
        hold = (
            update(Stations)
            .where(
                Stations.org_id == org_id,
                Stations.id == lease.station_id,
                Stations.token == lease.token - 1,
                or_(Stations.held_until.is_(None), Stations.held_until <= now - margin),
            )
            .values(
                token=lease.token,
                lease_id=lease.id,
                held_until=lease.expires_at,
                updated_at=now,
            )
            .returning(Stations.id)
        )
        settle = (
            update(StationLineEntries)
            .where(
                StationLineEntries.org_id == org_id,
                StationLineEntries.id == lease.entry_id,
                StationLineEntries.state == WAITING,
            )
            .values(
                state=EntryState.GRANTED.value,
                lease_id=lease.id,
                settled_at=now,
                updated_at=now,
                updated_by=lease.created_by,
            )
            .returning(StationLineEntries.id)
        )
        expire = (
            update(StationLeases)
            .where(
                StationLeases.org_id == org_id,
                StationLeases.station_id == lease.station_id,
                StationLeases.ended_at.is_(None),
            )
            .values(ended_at=now, ended=LeaseEnd.EXPIRED.value, updated_at=now)
        )
        async with self._session_for(hold, org_id=org_id) as session:
            if (await session.execute(hold)).scalar_one_or_none() is None:
                await session.rollback()
                return False
            if (
                lease.entry_id is not None
                and (await session.execute(settle)).scalar_one_or_none() is None
            ):
                await session.rollback()
                return False
            await session.execute(expire)
            session.add(to_row(lease, StationLeases, org_id=org_id))
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            try:
                await session.commit()
            except IntegrityError:
                # The second fence: a station holds one lease that has not
                # ended, whatever reached its row.
                await session.rollback()
                return False
            return True

    async def read_lease(self, org_id: UUID, lease_id: UUID) -> StationLease | None:
        stmt = select(StationLeases).where(
            StationLeases.org_id == org_id, StationLeases.id == lease_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, StationLease)

    async def renew_lease(
        self, org_id: UUID, lease_id: UUID, token: int, now: datetime, until: datetime
    ) -> StationLease | None:
        hold = (
            update(Stations)
            .where(
                Stations.org_id == org_id,
                Stations.lease_id == lease_id,
                Stations.token == token,
                Stations.held_until > now,
            )
            .values(held_until=until, updated_at=now)
            .returning(Stations.id)
        )
        extend = (
            update(StationLeases)
            .where(
                StationLeases.org_id == org_id,
                StationLeases.id == lease_id,
                StationLeases.ended_at.is_(None),
                StationLeases.expires_at > now,
            )
            .values(expires_at=until, updated_at=now)
            .returning(StationLeases)
        )
        async with self._session_for(hold, org_id=org_id) as session:
            if (await session.execute(hold)).scalar_one_or_none() is None:
                await session.rollback()
                return None
            row = (await session.execute(extend)).scalar_one_or_none()
            if row is None:
                await session.rollback()
                return None
            renewed = to_model(row, StationLease)
            await session.commit()
            return renewed

    async def end_lease(
        self,
        org_id: UUID,
        lease_id: UUID,
        at: datetime,
        end: LeaseEnd,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> StationLease | None:
        # The station's row first, as every write here takes it, so two
        # writers of one station never wait on each other in turn.
        free = (
            update(Stations)
            .where(Stations.org_id == org_id, Stations.lease_id == lease_id)
            .values(lease_id=None, held_until=None, updated_at=at)
        )
        stop = (
            update(StationLeases)
            .where(
                StationLeases.org_id == org_id,
                StationLeases.id == lease_id,
                StationLeases.ended_at.is_(None),
            )
            .values(ended_at=at, ended=end.value, updated_at=at)
            .returning(StationLeases)
        )
        async with self._session_for(free, org_id=org_id) as session:
            await session.execute(free)
            row = (await session.execute(stop)).scalar_one_or_none()
            if row is None:
                await session.rollback()
                return None
            ended = to_model(row, StationLease)
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()
            return ended

    # The jobs.

    async def create_job(
        self, org_id: UUID, job: StationJob, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(StationJobs, org_id, job, outbox_rows)

    async def read_job(self, org_id: UUID, job_id: UUID) -> StationJob | None:
        stmt = select(StationJobs).where(StationJobs.org_id == org_id, StationJobs.id == job_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, StationJob)

    async def write_job(
        self,
        org_id: UUID,
        job: StationJob,
        expected: JobState,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> bool:
        values = {k: v for k, v in to_values(job, StationJobs).items() if k != "id"}
        stmt = (
            update(StationJobs)
            .where(
                StationJobs.org_id == org_id,
                StationJobs.id == job.id,
                StationJobs.state == expected.value,
            )
            .values(**values)
            .returning(StationJobs.id)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            if (await session.execute(stmt)).scalar_one_or_none() is None:
                await session.rollback()
                return False
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()
            return True

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        purged = 0
        for table in PURGED_IN_ORDER:
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                purged += deleted(await session.execute(stmt))
                await session.commit()
        return purged
