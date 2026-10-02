"""The stations storage contract: labs, pools, and stations; a daemon's
credentials; the line; the leases; and the jobs. The grant is held here
over every impl: one live lease per station, by a conditional write that
fails while a live lease holds it, again only after its end and the
margin, with a token one above the station's. Two grants of one station
raced at once land one. The cases named in `CROSS_TENANT_CASES` are the
tenant fence's evidence: each one presents another tenant's identifier and
asserts that nothing is found and nothing changes."""

import asyncio
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import new_id, utcnow
from acme.om.exceptions import UniqueKeyTaken
from acme.om.stations.storage import StationsStorageInterface
from acme.om.stations.types.daemon import DaemonCredential
from acme.om.stations.types.job import JobState, StationCommand, StationJob
from acme.om.stations.types.lease import LeaseEnd, StationLease
from acme.om.stations.types.line import EntryState, LineEntry
from acme.om.stations.types.station import Lab, Station, StationPool

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_lab",
        "read_lab",
        "create_pool",
        "read_pool",
        "create_station",
        "read_station",
        "read_stations",
        "read_lab_stations",
        "create_daemon_credential",
        "rotate_daemon_credential",
        "end_daemon_credentials",
        "create_entry",
        "read_entry",
        "read_line",
        "read_waiting",
        "write_rank",
        "leave",
        "grant",
        "read_lease",
        "renew_lease",
        "end_lease",
        "create_job",
        "read_job",
        "write_job",
        "purge_tenant",
    }
)
"""Every method of `StationsStorageInterface` that takes a tenant has a case
in this module that presents another tenant's."""

MARGIN = timedelta(seconds=30)
HOLD = timedelta(minutes=5)


def made() -> dict[str, Any]:
    now = utcnow()
    actor = new_id()
    return {"created_at": now, "updated_at": now, "created_by": actor, "updated_by": actor}


def make_lab() -> Lab:
    return Lab(id=new_id(), **made(), name="lab-1")


def make_pool() -> StationPool:
    return StationPool(id=new_id(), **made(), name="pool-1", job_seconds=600)


def make_station(pool_id: UUID, capabilities: tuple[str, ...] = ()) -> Station:
    return Station(
        id=new_id(),
        **made(),
        lab_id=new_id(),
        pool_id=pool_id,
        name="station-1",
        capabilities=capabilities,
    )


def make_entry(
    pool_id: UUID, rank: float, station_id: UUID | None = None, session_id: UUID | None = None
) -> LineEntry:
    return LineEntry(
        id=new_id(),
        **made(),
        session_id=session_id or new_id(),
        pool_id=pool_id,
        station_id=station_id,
        project="acme/firmware",
        candidate="4f0405f",
        procedure="smoke",
        procedure_version="v1",
        principal=Principal(kind=PrincipalKind.PERSON, id=new_id()),
        rank=rank,
    )


def make_lease(
    station: Station, entry: LineEntry, at: datetime, hold: timedelta = HOLD
) -> StationLease:
    actor = new_id()
    return StationLease(
        id=new_id(),
        created_at=at,
        updated_at=at,
        created_by=actor,
        updated_by=actor,
        station_id=station.id,
        lab_id=station.lab_id,
        pool_id=station.pool_id,
        entry_id=entry.id,
        session_id=entry.session_id,
        token=station.token + 1,
        expires_at=at + hold,
    )


def make_credential(lab_id: UUID, lives: timedelta = timedelta(hours=1)) -> DaemonCredential:
    now = utcnow()
    return DaemonCredential(
        id=new_id(),
        created_at=now,
        lab_id=lab_id,
        issued_by=new_id(),
        digest=f"digest-{new_id()}",
        expires_at=now + lives,
    )


def make_job(lease: StationLease) -> StationJob:
    return StationJob(
        id=new_id(),
        **made(),
        lease_id=lease.id,
        station_id=lease.station_id,
        lab_id=lease.lab_id,
        session_id=lease.session_id,
        token=lease.token,
        project="acme/firmware",
        candidate="4f0405f",
        procedure="smoke",
        procedure_version="v1",
        commands=(StationCommand(operation="apply", parameters={"speed": 0.5}),),
    )


class StationsStorageContract:
    @pytest.fixture
    def storage(self) -> StationsStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def a_station(
        self, storage: StationsStorageInterface, org: UUID
    ) -> tuple[StationPool, Station]:
        pool = make_pool()
        assert await storage.create_pool(org, pool, ())
        station = make_station(pool.id)
        assert await storage.create_station(org, station, ())
        return pool, station

    async def waiting(
        self, storage: StationsStorageInterface, org: UUID, pool: StationPool, rank: float = 1.0
    ) -> LineEntry:
        entry = make_entry(pool.id, rank)
        assert await storage.create_entry(org, entry, ())
        return entry

    async def held(
        self, storage: StationsStorageInterface, org: UUID
    ) -> tuple[Station, StationLease]:
        pool, station = await self.a_station(storage, org)
        entry = await self.waiting(storage, org, pool)
        lease = make_lease(station, entry, utcnow())
        assert await storage.grant(org, lease, MARGIN, ())
        stored = await storage.read_station(org, station.id)
        assert stored is not None
        return stored, lease

    # Labs, pools, and stations.

    async def test_labs_pools_and_stations_round_trip(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        lab = make_lab()
        assert await storage.create_lab(org, lab, ())
        assert not await storage.create_lab(org, lab.model_copy(update={"name": "other"}), ())
        assert await storage.read_lab(org, lab.id) == lab
        pool, station = await self.a_station(storage, org)
        assert await storage.read_pool(org, pool.id) == pool
        assert await storage.read_station(org, station.id) == station
        second = make_station(pool.id, ("arm",))
        assert await storage.create_station(org, second, ())
        assert await storage.read_stations(org, pool.id, 10) == sorted(
            [station, second], key=lambda s: s.id
        )
        assert len(await storage.read_stations(org, pool.id, 1)) == 1
        assert await storage.read_lab_stations(org, station.lab_id, 10) == [station]
        assert await storage.read_lab_stations(org, new_id(), 10) == []

    async def test_create_and_read_lab_pool_and_station_of_another_tenant_find_nothing(
        self, storage: StationsStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        lab = make_lab()
        assert await storage.create_lab(org, lab, ())
        pool, station = await self.a_station(storage, org)
        assert not await storage.create_lab(other, lab, ())
        assert not await storage.create_pool(other, pool, ())
        assert not await storage.create_station(other, station, ())
        assert await storage.read_lab(other, lab.id) is None
        assert await storage.read_pool(other, pool.id) is None
        assert await storage.read_station(other, station.id) is None
        assert await storage.read_stations(other, pool.id, 10) == []
        assert await storage.read_lab_stations(other, station.lab_id, 10) == []

    # A daemon's credentials.

    async def test_a_daemon_credential_is_found_by_its_digest_with_its_tenant(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        credential = make_credential(new_id())
        await storage.create_daemon_credential(org, credential, ())
        assert await storage.read_daemon_credential_by_digest(credential.digest) == (
            org,
            credential,
        )
        assert await storage.read_daemon_credential_by_digest("digest-unknown") is None
        twin = make_credential(new_id()).model_copy(update={"digest": credential.digest})
        with pytest.raises(UniqueKeyTaken):
            await storage.create_daemon_credential(new_id(), twin, ())

    async def test_create_daemon_credential_under_another_tenant_is_refused(
        self, storage: StationsStorageInterface
    ) -> None:
        credential = make_credential(new_id())
        await storage.create_daemon_credential(new_id(), credential, ())
        with pytest.raises(UniqueKeyTaken):
            await storage.create_daemon_credential(new_id(), credential, ())

    async def test_rotate_daemon_credential_retires_the_old_and_lands_the_new(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        first = make_credential(new_id())
        await storage.create_daemon_credential(org, first, ())
        retire_at = utcnow() + timedelta(minutes=1)
        second = make_credential(first.lab_id)
        assert not await storage.rotate_daemon_credential(new_id(), first.id, retire_at, second)
        assert await storage.read_daemon_credential_by_digest(second.digest) is None
        assert await storage.rotate_daemon_credential(org, first.id, retire_at, second)
        found = await storage.read_daemon_credential_by_digest(first.digest)
        assert found is not None and found[1].expires_at == retire_at
        assert await storage.read_daemon_credential_by_digest(second.digest) == (org, second)
        # Another lab's credential is no retiring one of this lab.
        third = make_credential(new_id())
        assert not await storage.rotate_daemon_credential(org, second.id, retire_at, third)

    async def test_end_daemon_credentials_ends_the_labs_alone(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        lab_id = new_id()
        mine, theirs = make_credential(lab_id), make_credential(new_id())
        await storage.create_daemon_credential(org, mine, ())
        await storage.create_daemon_credential(org, theirs, ())
        at = utcnow()
        assert await storage.end_daemon_credentials(new_id(), lab_id, at, ()) == 0
        assert await storage.end_daemon_credentials(org, lab_id, at, ()) == 1
        ended = await storage.read_daemon_credential_by_digest(mine.digest)
        kept = await storage.read_daemon_credential_by_digest(theirs.digest)
        assert ended is not None and ended[1].expires_at == at
        assert kept is not None and kept[1].expires_at == theirs.expires_at

    # The line.

    async def test_a_line_is_read_in_rank_order_waiting_alone(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        pool, station = await self.a_station(storage, org)
        later = await self.waiting(storage, org, pool, rank=3.0)
        first = await self.waiting(storage, org, pool, rank=1.0)
        named = make_entry(pool.id, 2.0, station_id=station.id)
        assert await storage.create_entry(org, named, ())
        assert not await storage.create_entry(org, named, ())
        line = await storage.read_line(org, pool.id, 10)
        assert [entry.id for entry in line] == [first.id, named.id, later.id]
        assert await storage.read_entry(org, named.id) == named
        assert await storage.leave(org, (first.id,), utcnow(), new_id()) == 1
        assert await storage.leave(org, (first.id,), utcnow(), new_id()) == 0
        assert [entry.id for entry in await storage.read_line(org, pool.id, 10)] == [
            named.id,
            later.id,
        ]
        left = await storage.read_entry(org, first.id)
        assert left is not None and left.state is EntryState.LEFT and left.settled_at

    async def test_create_entry_and_read_line_of_another_tenant_find_nothing(
        self, storage: StationsStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        pool, _ = await self.a_station(storage, org)
        entry = await self.waiting(storage, org, pool)
        assert not await storage.create_entry(other, entry, ())
        assert await storage.read_entry(other, entry.id) is None
        assert await storage.read_line(other, pool.id, 10) == []
        assert await storage.read_waiting(other, entry.session_id, 10) == []

    async def test_a_sessions_waiting_entries_across_lines(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        session = new_id()
        first, second = make_pool(), make_pool()
        for pool in (first, second):
            assert await storage.create_pool(org, pool, ())
            assert await storage.create_entry(org, make_entry(pool.id, 1.0, session_id=session), ())
        assert await storage.create_entry(org, make_entry(first.id, 2.0), ())
        waiting = await storage.read_waiting(org, session, 10)
        assert {entry.pool_id for entry in waiting} == {first.id, second.id}

    async def test_write_rank_and_leave_touch_nothing_of_another_tenant(
        self, storage: StationsStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        pool, _ = await self.a_station(storage, org)
        entry = await self.waiting(storage, org, pool)
        assert not await storage.write_rank(other, entry.id, 9.0, utcnow(), new_id())
        assert await storage.leave(other, (entry.id,), utcnow(), new_id()) == 0
        assert await storage.read_entry(org, entry.id) == entry
        assert await storage.write_rank(org, entry.id, 9.0, utcnow(), new_id())
        moved = await storage.read_entry(org, entry.id)
        assert moved is not None and moved.rank == 9.0

    # The leases: one live lease per station.

    async def test_a_grant_holds_the_station_and_settles_the_entry(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        station, lease = await self.held(storage, org)
        assert (station.token, station.lease_id, station.held_until) == (
            1,
            lease.id,
            lease.expires_at,
        )
        assert await storage.read_lease(org, lease.id) == lease
        entry = await storage.read_entry(org, lease.entry_id)
        assert entry is not None and entry.state is EntryState.GRANTED
        assert entry.lease_id == lease.id

    async def test_a_live_lease_refuses_a_second_grant(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        station, lease = await self.held(storage, org)
        entry = await self.waiting(storage, org, make_pool_of(station))
        # Past its end, but within the margin: still not granted again.
        at = lease.expires_at + MARGIN / 2
        assert not await storage.grant(org, make_lease(station, entry, at), MARGIN, ())
        waiting = await storage.read_entry(org, entry.id)
        assert waiting is not None and waiting.state is EntryState.WAITING
        unchanged = await storage.read_station(org, station.id)
        assert unchanged == station

    async def test_a_lease_past_its_end_and_the_margin_is_granted_again_with_a_greater_token(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        station, lease = await self.held(storage, org)
        entry = await self.waiting(storage, org, make_pool_of(station))
        at = lease.expires_at + MARGIN
        second = make_lease(station, entry, at)
        assert second.token == lease.token + 1
        assert await storage.grant(org, second, MARGIN, ())
        expired = await storage.read_lease(org, lease.id)
        assert expired is not None and expired.ended is LeaseEnd.EXPIRED
        regranted = await storage.read_station(org, station.id)
        assert regranted is not None and regranted.token == 2

    async def test_a_grant_with_a_stale_token_or_a_settled_entry_lands_nothing(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        pool, station = await self.a_station(storage, org)
        entry = await self.waiting(storage, org, pool)
        stale = make_lease(station, entry, utcnow()).model_copy(update={"token": 5})
        assert not await storage.grant(org, stale, MARGIN, ())
        assert await storage.leave(org, (entry.id,), utcnow(), new_id()) == 1
        assert not await storage.grant(org, make_lease(station, entry, utcnow()), MARGIN, ())
        assert await storage.read_station(org, station.id) == station

    async def test_a_grant_that_settles_no_entry_holds_the_station_alone(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        pool, station = await self.a_station(storage, org)
        entry = await self.waiting(storage, org, pool)
        lease = make_lease(station, entry, utcnow()).model_copy(update={"entry_id": None})
        assert await storage.grant(org, lease, MARGIN, ())
        held = await storage.read_station(org, station.id)
        assert held is not None and (held.lease_id, held.token) == (lease.id, 1)
        untouched = await storage.read_entry(org, entry.id)
        assert untouched is not None and untouched.state is EntryState.WAITING
        # It is a live lease like any other: no second grant beside it.
        assert not await storage.grant(org, make_lease(held, entry, utcnow()), MARGIN, ())

    async def test_two_grants_of_one_station_raced_land_one(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        pool, station = await self.a_station(storage, org)
        first = await self.waiting(storage, org, pool, rank=1.0)
        second = await self.waiting(storage, org, pool, rank=2.0)
        at = utcnow()
        landed = await asyncio.gather(
            storage.grant(org, make_lease(station, first, at), MARGIN, ()),
            storage.grant(org, make_lease(station, second, at), MARGIN, ()),
        )
        assert sorted(landed) == [False, True]
        held = await storage.read_station(org, station.id)
        assert held is not None and held.token == 1
        settled = [await storage.read_entry(org, e.id) for e in (first, second)]
        assert sorted(e.state.value for e in settled if e is not None) == ["granted", "waiting"]

    async def test_grant_under_another_tenant_lands_nothing(
        self, storage: StationsStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        pool, station = await self.a_station(storage, org)
        entry = await self.waiting(storage, org, pool)
        assert not await storage.grant(other, make_lease(station, entry, utcnow()), MARGIN, ())
        assert await storage.read_station(org, station.id) == station

    async def test_a_renewal_holds_a_live_lease_alone(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        station, lease = await self.held(storage, org)
        now = utcnow()
        until = now + timedelta(minutes=10)
        assert await storage.renew_lease(new_id(), lease.id, lease.token, now, until) is None
        assert await storage.renew_lease(org, lease.id, lease.token + 1, now, until) is None
        renewed = await storage.renew_lease(org, lease.id, lease.token, now, until)
        assert renewed is not None and renewed.expires_at == until
        held = await storage.read_station(org, station.id)
        assert held is not None and held.held_until == until
        # Past its end, a lease is not renewed: it is gone, whoever waits.
        assert await storage.renew_lease(org, lease.id, lease.token, until, until + HOLD) is None

    async def test_end_lease_frees_the_station_once(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        station, lease = await self.held(storage, org)
        at = utcnow()
        assert await storage.end_lease(new_id(), lease.id, at, LeaseEnd.REVOKED, ()) is None
        ended = await storage.end_lease(org, lease.id, at, LeaseEnd.REVOKED, ())
        assert ended is not None and (ended.ended, ended.ended_at) == (LeaseEnd.REVOKED, at)
        assert await storage.end_lease(org, lease.id, at, LeaseEnd.RELEASED, ()) is None
        freed = await storage.read_station(org, station.id)
        assert freed is not None and (freed.lease_id, freed.held_until, freed.token) == (
            None,
            None,
            1,
        )
        assert await storage.renew_lease(org, lease.id, lease.token, at, at + HOLD) is None

    async def test_read_lease_of_another_tenant_finds_nothing(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        _, lease = await self.held(storage, org)
        assert await storage.read_lease(new_id(), lease.id) is None

    # The jobs.

    async def test_a_job_round_trips_and_moves_by_its_state(
        self, storage: StationsStorageInterface
    ) -> None:
        org = new_id()
        _, lease = await self.held(storage, org)
        job = make_job(lease)
        assert await storage.create_job(org, job, ())
        assert not await storage.create_job(org, job, ())
        assert await storage.read_job(org, job.id) == job
        running = job.model_copy(update={"state": JobState.RUNNING, "claim": {"id": "x"}})
        assert not await storage.write_job(org, running, JobState.RUNNING, ())
        assert await storage.write_job(org, running, JobState.QUEUED, ())
        assert await storage.read_job(org, job.id) == running

    async def test_create_read_and_write_job_of_another_tenant_find_nothing(
        self, storage: StationsStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        _, lease = await self.held(storage, org)
        job = make_job(lease)
        assert await storage.create_job(org, job, ())
        assert not await storage.create_job(other, job, ())
        assert await storage.read_job(other, job.id) is None
        running = job.model_copy(update={"state": JobState.RUNNING})
        assert not await storage.write_job(other, running, JobState.QUEUED, ())
        assert await storage.read_job(org, job.id) == job

    # The purge.

    async def test_purge_tenant_takes_its_rows_alone(
        self, storage: StationsStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        lab = make_lab()
        assert await storage.create_lab(org, lab, ())
        _, lease = await self.held(storage, org)
        assert await storage.create_job(org, make_job(lease), ())
        await storage.create_daemon_credential(org, make_credential(lab.id), ())
        kept_station, _ = await self.held(storage, other)
        assert await storage.purge_tenant(other, 1000) >= 4
        assert await storage.read_station(other, kept_station.id) is None
        assert await storage.read_lab(org, lab.id) == lab
        assert await storage.read_lease(org, lease.id) is not None
        assert await storage.purge_tenant(org, 1000) >= 6
        assert await storage.read_lab(org, lab.id) is None
        assert await storage.read_lease(org, lease.id) is None


def make_pool_of(station: Station) -> StationPool:
    """A pool value with the station's pool id, for an entry in its line."""
    return make_pool().model_copy(update={"id": station.pool_id})
