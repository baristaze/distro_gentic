"""Stations over memory: a session waits for a station in a line, parked,
and a free station goes to the first in line that waits, by a grant that
wakes it with the station and its lease. A session that no longer waits is
never granted and leaves every line it stood in. A lab's daemon calls with
a credential of its own kind, is handed only its lab's work, renews only
the lease of the job it runs, and its report lands the run as an execution
record, every refused command in it."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from contracts.step_storage import make_message, make_request

from acme.infra.impl.local import InfraLocalImpl
from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.agents.loop_rules import ended_step
from acme.om.base import new_id, utcnow
from acme.om.context import (
    AppContext,
    AppType,
    OperatorRole,
    RequestContext,
    Role,
    TenantContext,
)
from acme.om.evidence.types.provenance import Provenance
from acme.om.evidence.types.record import CaseTally, RunOutcome
from acme.om.exceptions import (
    CredentialExpired,
    InvalidCredential,
    NotAuthorized,
    NotFound,
    ValidationFailed,
)
from acme.om.hosts.exceptions import VersionBelowFloor
from acme.om.placement.rules import lab_lane
from acme.om.platform_agents.types.validation import ValidationStart, ValidationStatus
from acme.om.root import Managers, build_managers
from acme.om.stations.exceptions import JobSettled, LeaseEnded
from acme.om.stations.impl.manager import StationsManagerImpl, StationsOptions
from acme.om.stations.rules import DAEMON_CREDENTIAL_PREFIX, LINE_PARK
from acme.om.stations.storage.impl.memory import StationsStorageMemoryImpl
from acme.om.stations.types.daemon import DaemonIdentity
from acme.om.stations.types.job import JobReport, JobState, Refusal, RefusalReason, StationCommand
from acme.om.stations.types.lease import LeaseEnd, StationLease
from acme.om.stations.types.line import EntryState, LinePlace, StationAsk
from acme.om.stations.types.station import Lab, Station, StationPool
from acme.om.steps.types.header import InputHeader, LoopOutcome
from acme.om.steps.types.step import StepType
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tenancy.rules import CREDENTIAL_PREFIXES
from acme.om.work.storage.impl.memory import WorkStorageMemoryImpl
from acme.om.work.types.work_item import WorkItem, WorkKind, WorkStatus

APP = AppContext(type=AppType.PORTAL, version="portal@test")
DAEMON_APP = AppContext(type=AppType.API, version="station-daemon@test")


class Clock:
    def __init__(self) -> None:
        self.now = utcnow()

    def __call__(self) -> datetime:
        return self.now

    def advance(self, by: timedelta) -> None:
        self.now += by


def request(app: AppContext = DAEMON_APP) -> RequestContext:
    return RequestContext(request_id=new_id(), app=app)


@pytest.fixture
def storage() -> StorageMemoryImpl:
    return StorageMemoryImpl()


@pytest.fixture
def managers(tmp_path: Path, storage: StorageMemoryImpl) -> Managers:
    return build_managers(storage, InfraLocalImpl(tmp_path))


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def stations(managers: Managers, storage: StorageMemoryImpl, clock: Clock) -> StationsManagerImpl:
    """The stations manager the root builds, on a clock the case moves."""
    return StationsManagerImpl(
        storage.get_stations_storage(),
        managers.placement,
        managers.agent_sessions,
        managers.evidence,
        managers.platform_agents,
        managers.work,
        managers.tenancy,
        managers.outbox,
        StationsOptions(),
        clock=clock,
    )


async def an_owner(managers: Managers, slug: str = "ajax") -> TenantContext:
    owner, _ = await managers.tenancy.bootstrap(
        request(APP), slug.title(), slug, f"ann@{slug}.test", "Ann"
    )
    return owner


async def a_member(managers: Managers, slug: str, role: Role) -> TenantContext:
    owner, user, _ = await managers.tenancy.add_member(
        request(APP), slug, f"{role.value}@{slug}.test", role.value.title(), role
    )
    return await managers.tenancy.member_context(request(APP), owner.org_id, user.id)


def made(ctx: TenantContext) -> dict[str, Any]:
    now = utcnow()
    return {
        "created_at": now,
        "updated_at": now,
        "created_by": ctx.user_id,
        "updated_by": ctx.user_id,
    }


class Lab1:
    """One lab with a pool of two stations, as its owner made them."""

    def __init__(self, lab: Lab, pool: StationPool, first: Station, second: Station) -> None:
        self.lab, self.pool, self.first, self.second = lab, pool, first, second


async def a_lab(stations: StationsManagerImpl, owner: TenantContext) -> Lab1:
    lab = await stations.create_lab(owner, Lab(id=new_id(), **made(owner), name="lab-1"))
    pool = await stations.create_pool(
        owner, StationPool(id=new_id(), **made(owner), name="pool-1", job_seconds=600)
    )
    first, second = [
        await stations.add_station(
            owner,
            Station(
                id=new_id(),
                **made(owner),
                lab_id=lab.id,
                pool_id=pool.id,
                name=name,
                capabilities=("arm",),
            ),
        )
        for name in ("station-1", "station-2")
    ]
    return Lab1(lab, pool, first, second)


async def a_waiting_session(managers: Managers, ctx: TenantContext) -> UUID:
    """A session whose loop parked on the line, as the loop parks it."""
    sessions, steps = managers.agent_sessions, managers.steps
    session = await sessions.create_session(ctx, make_session())
    (message,) = await steps.append_inputs(ctx, session.id, [make_message(session.id)])
    epoch = await steps.begin_run(ctx, session.id)
    await steps.append_steps(
        ctx, session.id, epoch, [make_request(session.id, message.id, (message.id,))]
    )
    parked = await sessions.park(ctx, session.id, epoch, message.id, LINE_PARK)
    assert parked.status is SessionStatus.PARKED
    return session.id


async def a_running_session(managers: Managers, ctx: TenantContext) -> tuple[UUID, int, UUID]:
    sessions, steps = managers.agent_sessions, managers.steps
    session = await sessions.create_session(ctx, make_session())
    (message,) = await steps.append_inputs(ctx, session.id, [make_message(session.id)])
    epoch = await steps.begin_run(ctx, session.id)
    await steps.append_steps(
        ctx, session.id, epoch, [make_request(session.id, message.id, (message.id,))]
    )
    return session.id, epoch, message.id


async def end_loop(managers: Managers, ctx: TenantContext, session_id: UUID) -> None:
    """The session's loop ends: it no longer waits for anything."""
    steps = managers.steps
    epoch = await steps.begin_run(ctx, session_id)
    loop = (await steps.get_steps(ctx, session_id, 0, 1)).items[0].loop_id
    await steps.append_steps(
        ctx,
        session_id,
        epoch,
        [ended_step(new_id(), utcnow(), session_id, loop, LoopOutcome.CANCELLED)],
    )
    idle = await managers.agent_sessions.project_status(ctx, session_id)
    assert idle.status is SessionStatus.IDLE


def queued(storage: StorageMemoryImpl) -> list[WorkItem]:
    """Every item the queue holds, whatever its state."""
    work = storage.get_work_storage()
    assert isinstance(work, WorkStorageMemoryImpl)
    return [item for _, item in work._items.values()]  # pyright: ignore[reportPrivateUsage]


def ask(session_id: UUID, pool: StationPool, station: Station | None = None) -> StationAsk:
    return StationAsk(
        session_id=session_id,
        pool_id=pool.id,
        station_id=None if station is None else station.id,
        capabilities=("arm",),
        project="acme/firmware",
        candidate="4f0405f",
        procedure="smoke",
        procedure_version="v1",
    )


async def join(
    stations: StationsManagerImpl,
    ctx: TenantContext,
    session_id: UUID,
    pool: StationPool,
    station: Station | None = None,
) -> LinePlace:
    return await stations.join(ctx, new_id(), ask(session_id, pool, station))


async def held_by(
    stations: StationsManagerImpl, owner: TenantContext, station: Station
) -> StationLease | None:
    (found,) = [
        s for s in await stations.get_stations(owner, station.pool_id) if s.id == station.id
    ]
    if found.lease_id is None:
        return None
    return await stations._storage.read_lease(owner.org_id, found.lease_id)  # pyright: ignore[reportPrivateUsage]


# The line, and the grant.


async def test_a_free_station_goes_to_the_first_that_waits_and_wakes_it_with_its_lease(
    managers: Managers, stations: StationsManagerImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    session = await a_waiting_session(managers, owner)
    placed = await join(stations, owner, session, lab.pool, lab.first)
    assert placed.entry.state is EntryState.GRANTED
    lease = await held_by(stations, owner, lab.first)
    assert lease is not None and (lease.session_id, lease.token) == (session, 1)
    woken = await managers.agent_sessions.get_session(owner, session)
    assert woken.status is SessionStatus.PENDING and woken.park is None
    history = (await managers.steps.get_steps(owner, session, 0, 50)).items
    (event,) = [step for step in history if step.type is StepType.EVENT]
    assert isinstance(event.header, InputHeader) and event.header.waking
    assert str(lab.first.id) in event.as_text() and str(lease.id) in event.as_text()


async def test_a_session_in_line_sees_its_place_and_an_estimate(
    managers: Managers, stations: StationsManagerImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    holders = [await a_waiting_session(managers, owner) for _ in range(2)]
    for holder in holders:
        await join(stations, owner, holder, lab.pool)
    waiting = [await a_waiting_session(managers, owner) for _ in range(3)]
    places = [await join(stations, owner, session, lab.pool) for session in waiting]
    assert [p.position for p in places] == [0, 1, 2]
    # Two stations serve the line, each held a declared 600 seconds.
    assert [p.estimate_seconds for p in places] == [600, 600, 1200]
    assert [p.entry.session_id for p in await stations.get_line(owner, lab.pool.id)] == waiting
    for session in waiting:
        status = await managers.agent_sessions.get_session(owner, session)
        assert status.status is SessionStatus.PARKED


async def test_a_session_that_no_longer_waits_is_never_granted_and_leaves_every_line(
    managers: Managers, stations: StationsManagerImpl, storage: StorageMemoryImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    holder = await a_waiting_session(managers, owner)
    other_holder = await a_waiting_session(managers, owner)
    await join(stations, owner, holder, lab.pool, lab.first)
    await join(stations, owner, other_holder, lab.pool, lab.second)
    # Both stations are held. One session stands in two lines, the pool's
    # and the first station's, ahead of one that waits for the pool.
    gone = await a_waiting_session(managers, owner)
    await join(stations, owner, gone, lab.pool)
    await join(stations, owner, gone, lab.pool, lab.first)
    after = await a_waiting_session(managers, owner)
    await join(stations, owner, after, lab.pool)
    # Its loop ends: it no longer waits.
    await end_loop(managers, owner, gone)
    first_lease = await held_by(stations, owner, lab.first)
    assert first_lease is not None
    await stations.release_lease(owner, first_lease.id)
    granted = await held_by(stations, owner, lab.first)
    assert granted is not None and granted.session_id == after and granted.token == 2
    # It was granted nothing, was not woken, and stands in no line.
    assert (await managers.agent_sessions.get_session(owner, gone)).status is SessionStatus.IDLE
    history = (await managers.steps.get_steps(owner, gone, 0, 50)).items
    assert not [step for step in history if step.type is StepType.EVENT]
    held = storage.get_stations_storage()
    assert isinstance(held, StationsStorageMemoryImpl)
    entries = held._entries.values()  # pyright: ignore[reportPrivateUsage]
    states = {entry.state for _, entry in entries if entry.session_id == gone}
    assert states == {EntryState.LEFT}
    assert await stations.get_line(owner, lab.pool.id) == ()


async def test_a_session_that_joins_while_it_runs_is_granted_a_free_station_at_its_park(
    managers: Managers, stations: StationsManagerImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    session, epoch, loop_id = await a_running_session(managers, owner)
    placed = await join(stations, owner, session, lab.pool, lab.first)
    assert placed.entry.state is EntryState.WAITING
    assert await held_by(stations, owner, lab.first) is None
    # Its loop parks on the line, through the sessions every namespace is
    # handed: the park offers the station, and nobody else joins.
    woken = await managers.agent_sessions.park(owner, session, epoch, loop_id, LINE_PARK)
    lease = await held_by(stations, owner, lab.first)
    assert lease is not None and (lease.session_id, lease.token) == (session, 1)
    assert woken.status is SessionStatus.PENDING and woken.park is None


async def test_a_session_that_leaves_leaves_every_line_and_is_granted_nothing(
    managers: Managers, stations: StationsManagerImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    for station in (lab.first, lab.second):
        await join(stations, owner, await a_waiting_session(managers, owner), lab.pool, station)
    session = await a_waiting_session(managers, owner)
    await join(stations, owner, session, lab.pool)
    await join(stations, owner, session, lab.pool, lab.second)
    assert await stations.leave(owner, session) == 2
    lease = await held_by(stations, owner, lab.second)
    assert lease is not None
    await stations.release_lease(owner, lease.id)
    assert await held_by(stations, owner, lab.second) is None
    assert (await managers.agent_sessions.get_session(owner, session)).status is (
        SessionStatus.PARKED
    )


async def test_a_session_that_has_not_parked_yet_keeps_its_place_and_is_passed_over(
    managers: Managers, stations: StationsManagerImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    running, epoch, loop = await a_running_session(managers, owner)
    placed = await join(stations, owner, running, lab.pool, lab.first)
    assert placed.entry.state is EntryState.WAITING
    assert await held_by(stations, owner, lab.first) is None
    # Once it parks, the next free station is its own.
    await managers.agent_sessions.park(owner, running, epoch, loop, LINE_PARK)
    waiting = await a_waiting_session(managers, owner)
    await join(stations, owner, waiting, lab.pool, lab.first)
    lease = await held_by(stations, owner, lab.first)
    assert lease is not None and lease.session_id == running


async def test_one_station_is_granted_once_whoever_waits(
    managers: Managers, stations: StationsManagerImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    first, second = [await a_waiting_session(managers, owner) for _ in range(2)]
    a = await join(stations, owner, first, lab.pool, lab.first)
    b = await join(stations, owner, second, lab.pool, lab.first)
    assert (a.entry.state, b.entry.state) == (EntryState.GRANTED, EntryState.WAITING)
    held = [s for s in await stations.get_stations(owner, lab.pool.id) if s.id == lab.first.id]
    assert held[0].token == 1


async def test_a_person_who_manages_the_stations_reorders_a_line(
    managers: Managers, stations: StationsManagerImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    for station in (lab.first, lab.second):
        await join(stations, owner, await a_waiting_session(managers, owner), lab.pool, station)
    early, late = [await a_waiting_session(managers, owner) for _ in range(2)]
    first = await join(stations, owner, early, lab.pool)
    second = await join(stations, owner, late, lab.pool)
    member = await a_member(managers, "ajax", Role.MEMBER)
    with pytest.raises(NotAuthorized):
        await stations.reorder(member, second.entry.id, first.entry.id)
    moved = await stations.reorder(owner, second.entry.id, first.entry.id)
    assert moved.position == 0
    assert [p.entry.session_id for p in await stations.get_line(owner, lab.pool.id)] == [
        late,
        early,
    ]


async def test_a_revoked_lease_tells_its_session_and_goes_to_the_next(
    managers: Managers, stations: StationsManagerImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    holder = await a_waiting_session(managers, owner)
    await join(stations, owner, holder, lab.pool, lab.first)
    next_one = await a_waiting_session(managers, owner)
    await join(stations, owner, next_one, lab.pool, lab.first)
    lease = await held_by(stations, owner, lab.first)
    assert lease is not None
    member = await a_member(managers, "ajax", Role.MEMBER)
    with pytest.raises(NotAuthorized):
        await stations.revoke_lease(member, lease.id)
    revoked = await stations.revoke_lease(owner, lease.id)
    assert revoked.ended is LeaseEnd.REVOKED
    told = (await managers.steps.get_steps(owner, holder, 0, 50)).items
    assert any("revoked" in step.as_text() for step in told if step.type is StepType.EVENT)
    after = await held_by(stations, owner, lab.first)
    assert after is not None and (after.session_id, after.token) == (next_one, 2)
    with pytest.raises(LeaseEnded):
        await stations.release_lease(owner, lease.id)


# A lab's daemon.


async def a_daemon(
    stations: StationsManagerImpl, owner: TenantContext, lab: Lab
) -> tuple[str, DaemonIdentity]:
    issued = await stations.issue_daemon_credential(owner, lab.id)
    return issued.credential, await stations.authenticate(request(), issued.credential)


async def a_job(
    managers: Managers, stations: StationsManagerImpl, owner: TenantContext, lab: Lab1
) -> tuple[UUID, StationLease, UUID]:
    session = await a_waiting_session(managers, owner)
    await join(stations, owner, session, lab.pool, lab.first)
    lease = await held_by(stations, owner, lab.first)
    assert lease is not None
    commands = (
        StationCommand(operation="apply", parameters={"speed": 0.5}),
        StationCommand(operation="apply", parameters={"speed": 9.0}),
    )
    job = await stations.submit_job(owner, new_id(), lease.id, commands)
    return session, lease, job.id


async def test_a_daemon_calls_with_a_credential_of_its_own_kind(
    managers: Managers, stations: StationsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    issued = await stations.issue_daemon_credential(owner, lab.lab.id)
    assert issued.credential.startswith(DAEMON_CREDENTIAL_PREFIX)
    assert not any(issued.credential.startswith(p) for p in CREDENTIAL_PREFIXES)
    with pytest.raises(InvalidCredential):
        await managers.tenancy.authenticate(request(APP), issued.credential)
    key = await managers.tenancy.credentials.create_api_key(owner, "ci", Role.MEMBER)
    for credential in (key.key, DAEMON_CREDENTIAL_PREFIX + "forged", "hst_forged"):
        with pytest.raises(InvalidCredential):
            await stations.authenticate(request(), credential)
    daemon = await stations.authenticate(request(), issued.credential)
    assert (daemon.lab_id, daemon.org_id, daemon.issued_by) == (
        lab.lab.id,
        owner.org_id,
        owner.user_id,
    )
    # It trades the one a person handled for its own, which lives an hour.
    own = await stations.rotate(request(), daemon)
    assert own.expires_at == clock.now + StationsOptions().credential_ttl
    await stations.authenticate(request(), own.credential)
    member = await a_member(managers, "ajax", Role.MEMBER)
    with pytest.raises(NotAuthorized):
        await stations.issue_daemon_credential(member, lab.lab.id)
    # The first is live in its grace, and the revocation ends both.
    assert await stations.revoke_daemon(owner, lab.lab.id) == 2
    for credential in (issued.credential, own.credential):
        with pytest.raises(CredentialExpired):
            await stations.authenticate(request(), credential)


async def test_a_credential_rotates_once_and_a_second_rotation_revokes_the_daemon(
    managers: Managers, stations: StationsManagerImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    _, daemon = await a_daemon(stations, owner, lab.lab)
    own = await stations.rotate(request(), daemon)
    with pytest.raises(CredentialExpired):
        await stations.rotate(request(), daemon)
    with pytest.raises(CredentialExpired):
        await stations.authenticate(request(), own.credential)


async def test_a_rotated_credential_past_its_grace_revokes_the_daemon(
    managers: Managers, stations: StationsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    first, daemon = await a_daemon(stations, owner, lab.lab)
    own = await stations.rotate(request(), daemon)
    clock.advance(StationsOptions().rotation_grace)
    with pytest.raises(CredentialExpired):
        await stations.authenticate(request(), first)
    with pytest.raises(CredentialExpired):
        await stations.authenticate(request(), own.credential)


async def test_a_rotation_on_a_clock_behind_the_revocation_is_refused(
    managers: Managers, stations: StationsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    _, daemon = await a_daemon(stations, owner, lab.lab)
    assert await stations.revoke_daemon(owner, lab.lab.id) == 1
    # The daemon's rotation lands on a process whose clock trails the
    # revoker's by a second: the revoked credential's end is still ahead of
    # that clock, and its mark refuses the rotation all the same.
    clock.advance(timedelta(seconds=-1))
    with pytest.raises(CredentialExpired):
        await stations.rotate(request(), daemon)
    held = stations._storage  # pyright: ignore[reportPrivateUsage]
    assert isinstance(held, StationsStorageMemoryImpl)
    credentials = held._credentials.values()  # pyright: ignore[reportPrivateUsage]
    assert all(credential.revoked_at is not None for _, credential in credentials)


async def test_a_daemon_is_handed_its_labs_jobs_alone_under_the_floor(
    managers: Managers, stations: StationsManagerImpl
) -> None:
    owner = await an_owner(managers)
    ours, theirs = await a_lab(stations, owner), await a_lab(stations, owner)
    _, daemon = await a_daemon(stations, owner, ours.lab)
    _, lease, job_id = await a_job(managers, stations, owner, theirs)
    with pytest.raises(VersionBelowFloor):
        await stations.claim(request(), daemon, 0)
    assert await stations.claim(request(), daemon, 1) is None
    _, their_daemon = await a_daemon(stations, owner, theirs.lab)
    claimed = await stations.claim(request(), their_daemon, 1)
    assert claimed is not None and claimed.job is not None
    assert claimed.item.lane == lab_lane(theirs.lab.id)
    assert (claimed.job.id, claimed.job.token, claimed.job.state) == (
        job_id,
        lease.token,
        JobState.RUNNING,
    )
    assert claimed.item.claimed_by == f"daemon:{theirs.lab.id}"
    assert claimed.lease_seconds > 0
    # Another lab's daemon renews and reports nothing of it.
    with pytest.raises(NotFound):
        await stations.renew(request(), daemon, job_id)


async def test_the_daemons_report_lands_the_run_with_every_refused_command(
    managers: Managers, stations: StationsManagerImpl, storage: StorageMemoryImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    _, daemon = await a_daemon(stations, owner, lab.lab)
    session, lease, job_id = await a_job(managers, stations, owner, lab)
    claimed = await stations.claim(request(), daemon, 1)
    assert claimed is not None and claimed.job is not None
    left = await stations.renew(request(), daemon, job_id)
    assert (left.lease_id, left.token) == (lease.id, lease.token)
    refused = Refusal(
        operation="apply",
        reason=RefusalReason.LIMIT,
        detail="speed: 9.0 is above 1.0, past station-1's limit",
        refused_at=clock.now,
    )
    report = JobReport(
        run_id=new_id(),
        outcome=RunOutcome.ABORTED,
        started_at=clock.now,
        finished_at=clock.now,
        commands_run=1,
        refused=(refused,),
        abort=f"limit: {refused.detail}",
        adapter="twin:station-1",
        provenance=Provenance.TWIN,
        daemon_version="station-daemon@test",
    )
    finished = await stations.report(request(), daemon, job_id, report)
    assert (finished.state, finished.run_id) == (JobState.FINISHED, report.run_id)
    (run,) = (await managers.evidence.get_runs(owner, session, None, 10)).items
    assert run.id == report.run_id and run.outcome is RunOutcome.ABORTED
    assert run.provenance is Provenance.TWIN and run.executor == f"daemon:{lab.lab.id}"
    assert (run.version, run.check) == ("4f0405f", "smoke")
    assert run.metrics["refused"][0]["reason"] == "limit"
    # The claim is settled, and the lease waits its hold time for the next job.
    (item,) = [i for i in queued(storage) if i.target_id == job_id]
    assert item.status is WorkStatus.DONE
    held = await held_by(stations, owner, lab.first)
    assert held is not None and held.expires_at >= clock.now + timedelta(seconds=300)
    # A report again under the same run answers as stored; another is refused.
    assert await stations.report(request(), daemon, job_id, report) == finished
    with pytest.raises(JobSettled):
        await stations.report(
            request(), daemon, job_id, report.model_copy(update={"run_id": new_id()})
        )


async def test_a_job_under_an_ended_lease_is_refused_and_a_revoked_lease_is_renewed_never(
    managers: Managers, stations: StationsManagerImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    _, daemon = await a_daemon(stations, owner, lab.lab)
    _, lease, job_id = await a_job(managers, stations, owner, lab)
    await stations.claim(request(), daemon, 1)
    await stations.revoke_lease(owner, lease.id)
    with pytest.raises(LeaseEnded):
        await stations.renew(request(), daemon, job_id)
    with pytest.raises(LeaseEnded):
        await stations.submit_job(owner, new_id(), lease.id, (StationCommand(operation="apply"),))


async def test_a_held_lease_lasts_the_hold_time_while_its_session_waits(
    managers: Managers, stations: StationsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    holder = await a_waiting_session(managers, owner)
    await join(stations, owner, holder, lab.pool, lab.first)
    lease = await held_by(stations, owner, lab.first)
    assert lease is not None and lease.expires_at == clock.now + timedelta(seconds=300)
    waiting = await a_waiting_session(managers, owner)
    await join(stations, owner, waiting, lab.pool, lab.first)
    # Past its end and the margin, the next join's offer grants it again.
    clock.advance(timedelta(seconds=300) + StationsOptions().skew_margin)
    third = await a_waiting_session(managers, owner)
    await join(stations, owner, third, lab.pool, lab.second)
    await join(stations, owner, await a_waiting_session(managers, owner), lab.pool, lab.first)
    regranted = await held_by(stations, owner, lab.first)
    assert regranted is not None and (regranted.session_id, regranted.token) == (waiting, 2)
    expired = await stations._storage.read_lease(owner.org_id, lease.id)  # pyright: ignore[reportPrivateUsage]
    assert expired is not None and expired.ended is LeaseEnd.EXPIRED


async def test_a_lapsed_lease_goes_to_the_first_that_waits_at_the_sweep_and_once(
    managers: Managers, stations: StationsManagerImpl, clock: Clock
) -> None:
    """A lease its session never let go runs out at its hold time. With
    nobody joining after, the sweep grants the station to the first in its
    line who waits, under a greater token, in every tenant. The grant ends
    the lapsed lease, so a second pass grants nothing."""
    tenants: list[tuple[TenantContext, Lab1, StationLease, UUID, UUID]] = []
    for slug in ("ajax", "brio"):
        owner = await an_owner(managers, slug)
        lab = await a_lab(stations, owner)
        holder, first, second = [await a_waiting_session(managers, owner) for _ in range(3)]
        for session in (holder, first, second):
            await join(stations, owner, session, lab.pool, lab.first)
        lapsing = await held_by(stations, owner, lab.first)
        assert lapsing is not None and lapsing.session_id == holder
        tenants.append((owner, lab, lapsing, first, second))
    assert await stations.offer_lapsed(request()) == 0, "a live lease is no lapsed one"

    clock.advance(timedelta(seconds=300) + StationsOptions().skew_margin)
    assert await stations.offer_lapsed(request()) == 2
    assert await stations.offer_lapsed(request()) == 0, "two passes grant once"

    for owner, lab, lapsed, first, second in tenants:
        granted = await held_by(stations, owner, lab.first)
        assert granted is not None and granted.session_id == first
        assert granted.token == lapsed.token + 1
        ended = await stations._storage.read_lease(owner.org_id, lapsed.id)  # pyright: ignore[reportPrivateUsage]
        assert ended is not None and ended.ended is LeaseEnd.EXPIRED
        woken = await managers.agent_sessions.get_session(owner, first)
        assert woken.status is SessionStatus.PENDING and woken.park is None
        (place,) = await stations.get_line(owner, lab.pool.id)
        assert place.entry.session_id == second, "the next one keeps its place"


async def test_a_deleted_tenants_lapsed_stations_never_keep_a_live_ones_from_the_sweep(
    managers: Managers, storage: StorageMemoryImpl, clock: Clock
) -> None:
    """A deleted tenant's stations, lapsed longest, sort first at every
    pass, and the sweep skips them. With a batch of one, a pass still
    reaches past them and grants the live tenant's station."""
    stations = StationsManagerImpl(
        storage.get_stations_storage(),
        managers.placement,
        managers.agent_sessions,
        managers.evidence,
        managers.platform_agents,
        managers.work,
        managers.tenancy,
        managers.outbox,
        StationsOptions(sweep_batch=1),
        clock=clock,
    )
    labs: list[tuple[TenantContext, Lab1, UUID]] = []
    for slug in ("ajax", "brio"):
        owner = await an_owner(managers, slug)
        lab = await a_lab(stations, owner)
        holder, waiting = [await a_waiting_session(managers, owner) for _ in range(2)]
        for session in (holder, waiting):
            await join(stations, owner, session, lab.pool, lab.first)
        labs.append((owner, lab, waiting))
        clock.advance(timedelta(seconds=1))  # the first tenant's lease lapses first
    (gone, gone_lab, _), (live, live_lab, waiting) = labs
    tenancy = managers.tenancy
    await tenancy.bootstrap(
        request(APP), "Ops", "ops", "root@ops.test", "Root", operator_role=OperatorRole.WRITE
    )
    token = await tenancy.grant_operator_token(request(APP), "root@ops.test")
    admin = await tenancy.admit_operator(
        await tenancy.authenticate_login(request(APP), token.token)
    )
    await managers.tenancy_operator.delete_org(admin, gone.org_id)
    await tenancy.org.delete_closed_org(
        await tenancy.service_context(request(APP), gone.org_id, admin.identity_id)
    )
    clock.advance(timedelta(seconds=300) + StationsOptions().skew_margin)
    first = await stations._storage.read_lapsed(  # pyright: ignore[reportPrivateUsage]
        clock.now, StationsOptions().skew_margin, 1, frozenset()
    )
    assert first == [(gone.org_id, gone_lab.first.id)], "the gone tenant's sorts first"

    assert await stations.offer_lapsed(request()) == 1
    granted = await held_by(stations, live, live_lab.first)
    assert granted is not None and granted.session_id == waiting


async def test_a_running_job_claimed_again_is_settled_with_no_verdict_and_never_run_twice(
    managers: Managers, stations: StationsManagerImpl, storage: StorageMemoryImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    _, daemon = await a_daemon(stations, owner, lab.lab)
    session, lease, job_id = await a_job(managers, stations, owner, lab)
    first = await stations.claim(request(), daemon, 1)
    assert first is not None
    # The claim's answer never reached the daemon: the queue hands the same
    # item again, as its sweep does after a lost claim.
    work = managers.work
    await work.release(
        await managers.tenancy.service_context(request(), owner.org_id, owner.user_id),
        first.item,
    )
    assert await stations.claim(request(), daemon, 1) is None
    settled = await stations._storage.read_job(owner.org_id, job_id)  # pyright: ignore[reportPrivateUsage]
    assert settled is not None and settled.state is JobState.FINISHED
    (run,) = (await managers.evidence.get_runs(owner, session, None, 10)).items
    assert (run.id, run.outcome) == (settled.run_id, RunOutcome.ERRORED)
    (item,) = [item for item in queued(storage) if item.target_id == job_id]
    assert item.status is WorkStatus.DONE
    # The session keeps its station for its next job.
    held = await held_by(stations, owner, lab.first)
    assert held is not None and held.id == lease.id


async def test_a_job_queued_behind_another_stations_job_is_claimed_with_its_hold(
    managers: Managers, stations: StationsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    _, daemon = await a_daemon(stations, owner, lab.lab)
    leases = []
    for station in (lab.first, lab.second):
        await join(stations, owner, await a_waiting_session(managers, owner), lab.pool, station)
        lease = await held_by(stations, owner, station)
        assert lease is not None
        await stations.submit_job(owner, new_id(), lease.id, (StationCommand(operation="apply"),))
        leases.append(lease)
    first = await stations.claim(request(), daemon, 1)
    assert first is not None and first.lease_seconds > 0
    # The daemon runs the first station's job past the second's hold and
    # the margin, while the second's job waits on the lab's lane.
    clock.advance(timedelta(seconds=lab.second.hold_seconds) + StationsOptions().skew_margin)
    second = await stations.claim(request(), daemon, 1)
    assert second is not None and second.job is not None
    assert second.job.lease_id == leases[1].id
    assert second.lease_seconds == StationsOptions().job_lease.total_seconds()


# A validation session's run.


async def test_the_daemons_report_finishes_a_validation_session_with_no_model_call(
    managers: Managers, stations: StationsManagerImpl, storage: StorageMemoryImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    _, daemon = await a_daemon(stations, owner, lab.lab)
    validation = await managers.platform_agents.start_validation(
        owner,
        ValidationStart(
            id=new_id(),
            lab_id=lab.lab.id,
            check_name="measure",
            check_version="v2",
            parameters={"speed": 0.2},
        ),
    )
    claimed = await stations.claim(request(), daemon, 1)
    assert claimed is not None and claimed.job is not None
    job = claimed.job
    assert (job.id, job.session_id, job.procedure, job.candidate) == (
        validation.id,
        validation.id,
        "measure",
        "v2",
    )
    assert job.commands == (StationCommand(operation="measure", parameters={"speed": 0.2}),)
    # It holds its station by a lease of its own, as any grant does.
    lease = await stations._storage.read_lease(owner.org_id, job.lease_id)  # pyright: ignore[reportPrivateUsage]
    assert lease is not None and (lease.entry_id, lease.token) == (None, 1)
    # It takes no job but its own check.
    with pytest.raises(ValidationFailed):
        await stations.submit_job(owner, new_id(), lease.id, (StationCommand(operation="apply"),))
    report = JobReport(
        run_id=new_id(),
        outcome=RunOutcome.PASSED,
        started_at=clock.now,
        finished_at=clock.now,
        commands_run=1,
        cases=CaseTally(passed=1),
        adapter="twin:station-1",
        provenance=Provenance.TWIN,
        daemon_version="station-daemon@test",
    )
    await stations.report(request(), daemon, job.id, report)
    finished = await managers.platform_agents.get_validation(owner, validation.id)
    assert (finished.status, finished.run_id) == (ValidationStatus.FINISHED, report.run_id)
    (run,) = (await managers.evidence.get_runs(owner, validation.id, None, 10)).items
    assert (run.check, run.check_version, run.outcome) == ("measure", "v2", RunOutcome.PASSED)
    # No model was called: nothing asked for a loop, and its station is free.
    assert not [item for item in queued(storage) if item.kind is WorkKind.LOOP]
    assert await held_by(stations, owner, lab.first) is None
    assert await held_by(stations, owner, lab.second) is None


async def test_a_validation_whose_claim_was_lost_finishes_inconclusive(
    managers: Managers, stations: StationsManagerImpl, storage: StorageMemoryImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    _, daemon = await a_daemon(stations, owner, lab.lab)
    validation = await managers.platform_agents.start_validation(
        owner,
        ValidationStart(id=new_id(), lab_id=lab.lab.id, check_name="measure", check_version="v2"),
    )
    first = await stations.claim(request(), daemon, 1)
    assert first is not None and first.job is not None
    await managers.work.release(
        await managers.tenancy.service_context(request(), owner.org_id, owner.user_id),
        first.item,
    )
    assert await stations.claim(request(), daemon, 1) is None
    finished = await managers.platform_agents.get_validation(owner, validation.id)
    assert finished.status is ValidationStatus.FINISHED
    (run,) = (await managers.evidence.get_runs(owner, validation.id, None, 10)).items
    assert (run.id, run.outcome) == (finished.run_id, RunOutcome.ERRORED)
    # Its station goes back to the line.
    assert await held_by(stations, owner, lab.first) is None


async def test_a_validation_never_takes_a_station_a_session_waits_for(
    managers: Managers, stations: StationsManagerImpl
) -> None:
    owner = await an_owner(managers)
    lab = await a_lab(stations, owner)
    _, daemon = await a_daemon(stations, owner, lab.lab)
    # A session in the pool's line, not parked yet: no station is granted
    # to it, and none goes to a validation ahead of it.
    running, _, _ = await a_running_session(managers, owner)
    await join(stations, owner, running, lab.pool)
    validation = await managers.platform_agents.start_validation(
        owner,
        ValidationStart(id=new_id(), lab_id=lab.lab.id, check_name="measure", check_version="v2"),
    )
    assert await stations.claim(request(), daemon, 1) is None
    assert await held_by(stations, owner, lab.first) is None
    assert await held_by(stations, owner, lab.second) is None
    waiting = await managers.platform_agents.get_validation(owner, validation.id)
    assert waiting.status is ValidationStatus.QUEUED
