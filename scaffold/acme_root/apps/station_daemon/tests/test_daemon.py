"""A station daemon against the live app, in process: it trades its first
credential for its own; it runs a job's commands through the fence and the
owner's limits before the station's adapter; a refused command is in the
run's record, and on the disk until the platform recorded it; a token
below the highest it has seen is refused; a daemon cut off from the
platform runs its job to its lease's end on its own clock, stops the
station, and claims nothing, as one the platform fails does; a report the
platform fails holds the next claim until it lands; a refused credential
stops the station and keeps the report for the next one; and a revoked
lease stops the station."""

import stat
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from api_support import seed_request
from daemon_support import Monotonic, Stack

from acme.apps.station_daemon.config import load_credential
from acme.apps.station_daemon.daemon import CredentialRefused, LeaseClock, StationDaemon
from acme.client.types import StationJobView
from acme.om.base import new_id, utcnow
from acme.om.evidence.types.provenance import Provenance
from acme.om.evidence.types.record import ExecutionRecord, RunOutcome
from acme.om.platform_agents.types.validation import ValidationStart, ValidationStatus
from acme.om.stations.types.job import JobState, StationJob
from acme.om.stations.types.lease import StationLease
from acme.om.work.storage.impl.memory import WorkStorageMemoryImpl
from acme.om.work.types.work_item import WorkKind


async def runs_of(api: Stack, lease: StationLease) -> list[ExecutionRecord]:
    page = await api.container.managers.evidence.get_runs(api.owner, lease.session_id, None, 10)
    return list(page.items)


async def test_a_daemon_trades_its_first_credential_for_its_own(api: Stack, tmp_path: Path) -> None:
    daemon, _ = await api.daemon(tmp_path)
    held = daemon.credential
    assert held.token.startswith("std_") and held.lab_id == str(api.lab.id)
    path = tmp_path / "credential.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    kept = load_credential(path)
    assert kept is not None and kept.token == held.token
    # Started again with no first credential, it resumes with its own.
    again = StationDaemon(api.settings(tmp_path, None), {}, {}, api.client)
    await again.start()
    assert again.credential.token == held.token


async def test_a_command_past_a_limit_is_refused_and_recorded_in_the_run(
    api: Stack, tmp_path: Path
) -> None:
    daemon, twin = await api.daemon(tmp_path)
    lease = await api.granted()
    await api.job(lease, 0.5, 9.0, 0.2)
    ran = await daemon.tick()
    assert ran is not None and ran.reported
    # The first command ran; the one past the limit did not, and ended the job.
    assert twin.calls == ["stop:hold", "restore", "apply"]
    assert twin.state["speed"] == 0.5
    (refused,) = ran.refused
    assert refused["reason"] == "limit" and refused["detail"].startswith("speed: 9.0")
    (run,) = await runs_of(api, lease)
    assert run.outcome is RunOutcome.ABORTED and run.abort and run.abort.startswith("limit")
    assert run.metrics["refused"][0]["detail"] == refused["detail"]
    assert run.provenance is Provenance.TWIN
    assert daemon.journal.pending() == []


async def test_a_refusal_stays_on_the_disk_until_the_platform_records_it(
    api: Stack, tmp_path: Path
) -> None:
    daemon, _ = await api.daemon(tmp_path)
    lease = await api.granted()
    await api.job(lease, 5.0)
    claimed = await api.client(daemon.credential.token).claim_station_work(1)
    assert claimed.job is not None
    api.transport.cut = True
    ran = await daemon.run(claimed.job, clock_for(daemon, claimed.lease_seconds or 0.0))
    assert not ran.reported and daemon.offline
    ((job_id, report),) = daemon.journal.pending()
    assert job_id == str(claimed.job.id) and report["refused"][0]["reason"] == "limit"
    assert await runs_of(api, lease) == []
    # The platform answers again: the next turn sends what the disk holds.
    api.transport.cut = False
    assert await daemon.tick() is None
    (run,) = await runs_of(api, lease)
    assert str(run.id) == report["run_id"] and run.outcome is RunOutcome.ABORTED
    assert daemon.journal.pending() == []


async def test_a_token_below_the_highest_seen_is_refused_and_a_higher_one_stops_first(
    api: Stack, tmp_path: Path
) -> None:
    daemon, twin = await api.daemon(tmp_path)
    first = await api.granted()
    await api.job(first, 0.3)
    old = await daemon.tick()
    assert old is not None and old.reported and twin.calls == ["stop:hold", "restore", "apply"]
    stale = await api.container.managers.stations.revoke_lease(api.owner, first.id)
    second = await api.granted()
    assert second.token == stale.token + 1
    await api.job(second, 0.4)
    twin.calls.clear()
    new = await daemon.tick()
    assert new is not None and new.reported
    # Before the higher token, the station took its controlled stop and its
    # baseline: nothing the last holder set carries over.
    assert twin.calls == ["stop:hold", "restore", "apply"]
    assert daemon.fence.highest(api.station.id) == second.token
    # A command under the lower token is refused, and runs nothing; a
    # restart forgets no token.
    twin.calls.clear()
    old_job = await stale_job(api, daemon, old.job_id)
    refused = await daemon.run(old_job, clock_for(daemon, 60.0))
    assert refused.refused[0]["reason"] == "fenced" and twin.calls == []
    again = StationDaemon(
        api.settings(tmp_path, None),
        {},
        {},
        api.client,
    )
    assert again.fence.highest(api.station.id) == second.token


async def test_a_daemon_cut_off_runs_its_job_to_its_lease_end_stops_and_claims_nothing(
    api: Stack, tmp_path: Path
) -> None:
    clock = Monotonic()
    # Each operation takes 20 seconds on the daemon's own clock; the lease
    # holds the station 60.
    daemon, twin = await api.daemon(tmp_path, clock=clock, seconds=20.0)
    lease = await api.granted()
    await api.job(lease, 0.1, 0.2, 0.3, 0.4, 0.5)
    claimed = await api.client(daemon.credential.token).claim_station_work(1)
    assert claimed.job is not None and claimed.lease_seconds is not None
    assert 59.0 < claimed.lease_seconds <= 60.0
    api.transport.cut = True
    ran = await daemon.run(claimed.job, clock_for(daemon, claimed.lease_seconds))
    # Three ran inside the lease; the fourth met its end, on this host's
    # clock, and the station took its controlled stop.
    assert twin.calls == ["stop:hold", "restore", "apply", "apply", "apply", "stop:hold"]
    assert ran.refused[0]["reason"] == "lease_ended"
    assert ran.report["commands_run"] == 3 and not ran.reported
    # Cut off, it claims no new job, and the report waits on its disk.
    await api.job(lease, 0.1)
    assert await daemon.tick() is None and daemon.offline
    assert len(daemon.journal.pending()) == 1
    api.transport.cut = False
    await daemon.flush()
    assert daemon.journal.pending() == []
    (run,) = await runs_of(api, lease)
    assert run.outcome is RunOutcome.ABORTED and run.metrics["commands_run"] == 3


async def test_a_failing_renewal_is_asked_again_and_the_job_runs_to_its_lease(
    api: Stack, tmp_path: Path
) -> None:
    clock = Monotonic()
    daemon, twin = await api.daemon(tmp_path, clock=clock, seconds=20.0)
    lease = await api.granted()
    await api.job(lease, 0.1, 0.2, 0.3, 0.4)
    claimed = await api.client(daemon.credential.token).claim_station_work(1)
    assert claimed.job is not None
    # The platform fails every renewal and every report with a 503.
    api.transport.failing = {"/renewals": 503, "/reports": 503}
    ran = await daemon.run(claimed.job, clock_for(daemon, claimed.lease_seconds or 0.0))
    # The job ran on to its lease's end, and the station took its stop.
    assert twin.calls == ["stop:hold", "restore", "apply", "apply", "apply", "stop:hold"]
    assert ran.refused[0]["reason"] == "lease_ended" and not ran.reported
    assert len(daemon.journal.pending()) == 1
    api.transport.failing = {}
    assert await daemon.flush() == 1
    (run,) = await runs_of(api, lease)
    assert run.outcome is RunOutcome.ABORTED and run.metrics["commands_run"] == 3


async def test_a_report_the_platform_fails_holds_the_next_claim_until_it_lands(
    api: Stack, tmp_path: Path
) -> None:
    daemon, _ = await api.daemon(tmp_path)
    lease = await api.granted()
    job_id = await api.job(lease, 0.1, 0.2)
    # The platform fails every report with a 503; its claims still answer.
    api.transport.failing = {"/reports": 503}
    ran = await daemon.tick()
    assert ran is not None and not ran.reported and ran.report["commands_run"] == 2
    # The report waits past the job's claim: the sweep hands its item back.
    work = api.container.storage.get_work_storage()
    assert isinstance(work, WorkStorageMemoryImpl)
    held = work._items  # pyright: ignore[reportPrivateUsage]
    ((org_id, item),) = [row for row in held.values() if row[1].target_id == job_id]
    lapsed = utcnow() - timedelta(seconds=1)
    held[item.id] = (org_id, item.model_copy(update={"lease_expires_at": lapsed}))
    assert await api.container.managers.work.requeue_stale(seed_request(), limit=10) == 1
    # While the report waits on its disk, the daemon claims nothing, so
    # nothing settles the running job without it.
    assert await daemon.tick() is None and daemon.offline
    assert len(daemon.journal.pending()) == 1
    assert (await stored_job(api, job_id)).state is JobState.RUNNING
    # The platform answers again: the report lands, and the run is the real one.
    api.transport.failing = {}
    assert await daemon.tick() is None
    (run,) = await runs_of(api, lease)
    assert str(run.id) == ran.report["run_id"] and run.outcome is RunOutcome.PASSED
    assert run.metrics["commands_run"] == 2
    finished = await stored_job(api, job_id)
    assert finished.state is JobState.FINISHED and str(finished.run_id) == ran.report["run_id"]
    assert daemon.journal.pending() == [] and list((tmp_path / "reports").iterdir()) == []


async def test_a_refused_credential_mid_job_stops_the_station_and_keeps_the_report(
    api: Stack, tmp_path: Path
) -> None:
    clock = Monotonic()
    daemon, twin = await api.daemon(tmp_path, clock=clock, seconds=20.0)
    lease = await api.granted()
    await api.job(lease, 0.1, 0.2, 0.3)
    claimed = await api.client(daemon.credential.token).claim_station_work(1)
    assert claimed.job is not None
    await api.container.managers.stations.revoke_daemon(api.owner, api.lab.id)
    with pytest.raises(CredentialRefused):
        await daemon.run(claimed.job, clock_for(daemon, claimed.lease_seconds or 0.0))
    # Two ran before the renewal was due; its credential was refused, and
    # the station took its controlled stop.
    assert twin.calls == ["stop:hold", "restore", "apply", "apply", "stop:hold"]
    ((job_id, report),) = daemon.journal.pending()
    assert job_id == str(claimed.job.id) and report["refused"][0]["reason"] == "lease_ended"
    assert not (tmp_path / "credential.json").exists()
    # Started again with a first credential its owner issues, it sends what
    # the disk holds.
    again = StationDaemon(api.settings(tmp_path, await api.credential()), {}, {}, api.client)
    await again.start()
    assert await again.tick() is None
    (run,) = await runs_of(api, lease)
    assert str(run.id) == report["run_id"] and run.outcome is RunOutcome.ABORTED
    assert again.journal.pending() == []


async def test_an_idle_daemon_waits_out_a_failing_claim_and_stops_on_a_refused_one(
    api: Stack, tmp_path: Path
) -> None:
    daemon, _ = await api.daemon(tmp_path)
    api.transport.failing = {"/claims": 503}
    assert await daemon.tick() is None and daemon.offline
    api.transport.failing = {}
    await api.container.managers.stations.revoke_daemon(api.owner, api.lab.id)
    with pytest.raises(CredentialRefused):
        await daemon.tick()


async def test_a_credential_that_would_lapse_in_a_job_is_rotated_at_its_start(
    api: Stack, tmp_path: Path
) -> None:
    daemon, _ = await api.daemon(tmp_path)
    lease = await api.granted()
    await api.job(lease, 0.1)
    claimed = await api.client(daemon.credential.token).claim_station_work(1)
    assert claimed.job is not None
    held = daemon.credential
    # On the daemon's clock the credential ends ten seconds into the lease.
    daemon._now = lambda: held.expires_at - timedelta(seconds=10)  # pyright: ignore[reportPrivateUsage]
    ran = await daemon.run(claimed.job, clock_for(daemon, claimed.lease_seconds or 0.0))
    assert ran.reported and daemon.credential.token != held.token


async def test_a_revoked_lease_stops_the_station_at_the_daemons_next_renewal(
    api: Stack, tmp_path: Path
) -> None:
    clock = Monotonic()
    daemon, twin = await api.daemon(tmp_path, clock=clock, seconds=20.0)
    lease = await api.granted()
    await api.job(lease, 0.1, 0.2, 0.3)
    claimed = await api.client(daemon.credential.token).claim_station_work(1)
    assert claimed.job is not None
    await api.container.managers.stations.revoke_lease(api.owner, lease.id)
    ran = await daemon.run(claimed.job, clock_for(daemon, claimed.lease_seconds or 0.0))
    # Two ran before the renewal was due; the renewal was refused, and the
    # station took its controlled stop.
    assert twin.calls == ["stop:hold", "restore", "apply", "apply", "stop:hold"]
    assert ran.refused[0]["reason"] == "lease_ended" and ran.reported


async def test_the_daemons_report_finishes_a_validation_session_with_no_model_call(
    api: Stack, tmp_path: Path
) -> None:
    daemon, twin = await api.daemon(tmp_path)
    validations = api.container.managers.platform_agents
    started = await validations.start_validation(
        api.owner,
        ValidationStart(
            id=new_id(),
            lab_id=api.lab.id,
            check_name="measure",
            check_version="v2",
            parameters={"speed": 0.2},
        ),
    )
    ran = await daemon.tick()
    assert ran is not None and ran.reported and ran.refused == []
    assert twin.calls == ["stop:hold", "restore", "measure"]
    finished = await validations.get_validation(api.owner, started.id)
    assert finished.status is ValidationStatus.FINISHED
    assert str(finished.run_id) == ran.report["run_id"]
    # Nothing in its path asked for a loop, so no model was called.
    work = api.container.storage.get_work_storage()
    assert isinstance(work, WorkStorageMemoryImpl)
    items = [item for _, item in work._items.values()]  # pyright: ignore[reportPrivateUsage]
    assert [item.kind for item in items] == [WorkKind.STATION]


def clock_for(daemon: StationDaemon, seconds: float) -> LeaseClock:
    """A lease's deadlines from now on the daemon's clock, as a claim sets
    them."""
    now = daemon._monotonic()  # pyright: ignore[reportPrivateUsage]
    return LeaseClock(deadline=now + seconds, renew_at=now + seconds / 2)


async def stored_job(api: Stack, job_id: UUID) -> StationJob:
    """A job as the platform holds it."""
    job = await api.container.managers.stations._storage.read_job(  # pyright: ignore[reportAttributeAccessIssue]
        api.owner.org_id, job_id
    )
    assert job is not None
    return job


async def stale_job(api: Stack, daemon: StationDaemon, job_id: str) -> StationJobView:
    """A job as the daemon was handed it, under the token it held then."""
    job = await stored_job(api, UUID(job_id))
    return StationJobView.model_validate(
        {
            **job.model_dump(mode="json"),
            "fencing_token": job.token,
            "commands": [command.model_dump(mode="json") for command in job.commands],
            "state": job.state.value,
        }
    )
