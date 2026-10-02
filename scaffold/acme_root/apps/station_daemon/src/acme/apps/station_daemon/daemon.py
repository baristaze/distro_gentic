"""A station daemon's life as a client of the gateway, inside its owner's
wall. It picks up its credential, or trades the first one its owner gave
it for one of its own, and rotates it at half its life. Then it claims its
lab's station work and runs each job through the station's guard and the
station's adapter, and nothing else. Every connection is opened from here,
outward, and the daemon grants itself nothing: a job reaches it only by a
claim, and its lease only by a grant.

The daemon holds logic, as the guard nearest the resource must (ADR
2006):

- **The fence.** Every command is checked against the highest token the
  daemon has seen for its station (`fence.Fence`); a lower one is
  refused, and a higher one is taken only after the station's controlled
  stop and its baseline.
- **The limits.** Every command is held to the owner's limits
  (`stations.refusal`), which nothing the platform sends can raise.
- **The lease's time.** The platform answers how many seconds a lease has
  left, never until when, and the daemon times them on its own monotonic
  clock, from the moment it asked. Past that, it runs nothing under the
  lease and takes the controlled stop.
- **The platform gone.** A daemon that cannot reach the platform lets the
  current job run to its lease's end, then stops the station, and claims
  no new job until the platform answers again.
- **The evidence.** A job's report, every refused command in it, is on
  the disk before it is sent, and stays there until the platform recorded
  it (`journal.Journal`)."""

import logging
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx

from acme.apps.station_daemon.adapter import StationAdapterInterface
from acme.apps.station_daemon.config import Credential, Settings, load_credential, save_credential
from acme.apps.station_daemon.fence import Admission, Fence
from acme.apps.station_daemon.journal import Journal
from acme.apps.station_daemon.stations import Station, refusal
from acme.client.client import ApiClient, ApiError
from acme.client.types import IssuedDaemonCredentialView, StationJobView

log = logging.getLogger(__name__)

STATION_VERSION = 1
"""The version of `station` work this build of the daemon reads."""

FENCED = "fenced"
LEASE_ENDED = "lease_ended"
UNKNOWN_OPERATION = "unknown_operation"
GONE_FOR_GOOD = frozenset({"lease_ended", "job_settled", "not_found"})
"""The refusals of a renewal that say the lease will not come back."""


class NotEnrolled(RuntimeError):
    """The daemon holds no live credential and was given none: its owner
    issues one for its lab, and the daemon is started with it once."""


ClientFactory = Callable[[str | None], ApiClient]
"""Builds the client for a bearer: the daemon's credential, or None."""


@dataclass
class LeaseClock:
    """A job's lease as the daemon keeps it: deadlines on its own monotonic
    clock, and whether the platform said it ended."""

    deadline: float
    renew_at: float
    gone: bool = False


@dataclass
class Ran:
    """What became of one job: its report, and whether the platform has
    recorded it yet."""

    job_id: str
    report: dict[str, Any]
    reported: bool
    refused: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])


class StationDaemon:
    def __init__(
        self,
        settings: Settings,
        stations: Mapping[UUID, Station],
        adapters: Mapping[UUID, StationAdapterInterface],
        client_for: ClientFactory,
        *,
        version: str = "station-daemon@dev",
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._stations = stations
        self._adapters = adapters
        self._client_for = client_for
        self._version = version
        self._monotonic = monotonic
        self._now = now
        self._fence = Fence(settings.fence_path)
        self._journal = Journal(settings.reports_path)
        self._credential: Credential | None = None
        self.offline = False

    @property
    def credential(self) -> Credential:
        if self._credential is None:
            raise RuntimeError("the daemon has not started")
        return self._credential

    @property
    def fence(self) -> Fence:
        return self._fence

    @property
    def journal(self) -> Journal:
        return self._journal

    async def start(self) -> None:
        """Picks up the credential it holds, or trades the one its owner gave
        it for one of its own, so the one a person handled ends at once."""
        held = load_credential(self._settings.credential_path)
        if (
            held is not None
            and held.api_url == self._settings.api_url
            and not held.ended(self._now())
        ):
            self._credential = held
            return
        first = self._settings.first_credential
        if not first:
            raise NotEnrolled("no live credential and no ACME_DAEMON_CREDENTIAL to start with")
        async with self._client_for(first) as client:
            issued = await client.rotate_daemon_credential()
        self._keep(issued)
        log.info("serving lab %s", issued.lab_id)

    async def tick(self) -> Ran | None:
        """One turn: rotate when due, send what the platform has not recorded
        yet, then claim one job and run it. A daemon that cannot reach the
        platform claims nothing."""
        try:
            await self._rotate_if_due()
            await self.flush()
            async with self._client_for(self.credential.token) as client:
                asked = self._monotonic()
                answer = await client.claim_station_work(STATION_VERSION)
        except httpx.TransportError as error:
            self._lost(error)
            return None
        self.offline = False
        if answer.item is None:
            return None
        if answer.job is None:
            log.warning("item %s names no station job; it is left to its lease", answer.item.id)
            return None
        seconds = answer.lease_seconds or 0.0
        lease = LeaseClock(deadline=asked + seconds, renew_at=asked + seconds / 2)
        return await self.run(answer.job, lease)

    async def flush(self) -> int:
        """Sends every report the platform has not recorded; returns how many
        it recorded now. A transport failure is raised, and what is left
        stays on the disk."""
        recorded = 0
        for job_id, report in self._journal.pending():
            if await self._send(job_id, report):
                recorded += 1
        return recorded

    async def run(self, job: StationJobView, lease: LeaseClock) -> Ran:
        """Runs a job's commands in order, each through the guard first. The
        first refusal ends the job; a lease that ended stops the station."""
        started = self._now()
        refused: list[dict[str, Any]] = []
        ran = passed = failed = 0
        station = self._stations.get(job.station_id)
        adapter = self._adapters.get(job.station_id)
        for command in job.commands:
            if station is None or adapter is None:
                refused.append(
                    self._refused(command.operation, UNKNOWN_OPERATION, "no such station here")
                )
                break
            await self._renew_if_due(job, lease)
            why = await self._guard(
                station, adapter, job, lease, command.operation, command.parameters
            )
            if why is not None:
                refused.append(self._refused(command.operation, *why))
                break
            outcome = await adapter.run(command.operation, command.parameters)
            ran += 1
            passed, failed = passed + outcome.ok, failed + (not outcome.ok)
        if adapter is not None and (lease.gone or self._monotonic() >= lease.deadline):
            # The station takes its controlled stop: a lease that ended runs
            # nothing more, whoever holds the station next.
            await adapter.stop()
        report = self._report(job, adapter, started, ran, passed, failed, refused)
        self._journal.keep(str(job.id), report)
        try:
            reported = await self._send(str(job.id), report)
        except httpx.TransportError as error:
            self._lost(error)
            reported = False
        return Ran(job_id=str(job.id), report=report, reported=reported, refused=refused)

    async def _guard(
        self,
        station: Station,
        adapter: StationAdapterInterface,
        job: StationJobView,
        lease: LeaseClock,
        operation: str,
        parameters: Mapping[str, Any],
    ) -> tuple[str, str] | None:
        """Why the command does not run, or None when it may: the fence, the
        lease's time, then the owner's limits."""

        async def stop_and_restore() -> None:
            await adapter.stop()
            await adapter.restore()

        admitted = await self._fence.admit(station.id, job.fencing_token, stop_and_restore)
        if admitted is Admission.FENCED:
            highest = self._fence.highest(station.id)
            return FENCED, f"token {job.fencing_token} is below {highest}, the highest seen"
        if lease.gone:
            return LEASE_ENDED, "the platform ended the lease"
        if self._monotonic() >= lease.deadline:
            return LEASE_ENDED, "the lease ran out on this host's clock"
        return refusal(station, operation, parameters)

    async def _renew_if_due(self, job: StationJobView, lease: LeaseClock) -> None:
        """Renews the lease at half its time, as the executor of the job.
        A platform that cannot be reached leaves the deadline where it was;
        one that says the lease ended marks it gone."""
        if lease.gone or self._monotonic() < lease.renew_at:
            return
        asked = self._monotonic()
        try:
            async with self._client_for(self.credential.token) as client:
                left = await client.renew_station_job(job.id)
        except httpx.TransportError as error:
            self._lost(error)
            # Asked again at the next command, never past the deadline.
            lease.renew_at = asked + max(0.0, (lease.deadline - asked) / 2)
            return
        except ApiError as error:
            if error.code in GONE_FOR_GOOD:
                lease.gone = True
                return
            raise
        self.offline = False
        lease.deadline = asked + left.seconds
        lease.renew_at = asked + left.seconds / 2

    async def _send(self, job_id: str, report: dict[str, Any]) -> bool:
        """Sends one report. Recorded, it leaves the disk; refused for good,
        it is set aside there. A transport failure is raised."""
        try:
            async with self._client_for(self.credential.token) as client:
                await client.report_station_job(UUID(job_id), report)
        except ApiError as error:
            if error.status >= 500 or error.status == 429:
                return False
            log.error("the report of job %s was refused: %s; it is set aside", job_id, error)
            self._journal.set_aside(job_id)
            return False
        self._journal.sent(job_id)
        return True

    async def _rotate_if_due(self) -> None:
        if not self.credential.due(self._now()):
            return
        async with self._client_for(self.credential.token) as client:
            issued = await client.rotate_daemon_credential()
        self._keep(issued)

    def _refused(self, operation: str, reason: str, detail: str) -> dict[str, Any]:
        log.warning("refused %s: %s: %s", operation, reason, detail)
        return {
            "operation": operation[:100],
            "reason": reason,
            "detail": detail[:500],
            "refused_at": self._now().isoformat(),
        }

    def _report(
        self,
        job: StationJobView,
        adapter: StationAdapterInterface | None,
        started: datetime,
        ran: int,
        passed: int,
        failed: int,
        refused: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if refused:
            outcome = "aborted"
            first = refused[0]
            abort: str | None = f"{first['reason']}: {first['detail']}"[:500]
        else:
            outcome = "failed" if failed else "passed"
            abort = None
        return {
            "run_id": str(uuid.uuid7()),
            "outcome": outcome,
            "started_at": started.isoformat(),
            "finished_at": self._now().isoformat(),
            "commands_run": ran,
            "cases": {"passed": passed, "failed": failed, "skipped": len(job.commands) - ran},
            "refused": refused,
            "abort": abort,
            "adapter": adapter.name if adapter is not None else "none",
            "provenance": adapter.provenance if adapter is not None else "unavailable",
            "daemon_version": self._version,
        }

    def _lost(self, error: Exception) -> None:
        if not self.offline:
            log.warning("the platform cannot be reached: %s", error)
        self.offline = True

    def _keep(self, issued: IssuedDaemonCredentialView) -> None:
        if issued.token is None:
            raise NotEnrolled("the platform answered no credential")
        self._credential = Credential(
            api_url=self._settings.api_url,
            token=issued.token,
            credential_id=str(issued.credential_id),
            lab_id=str(issued.lab_id),
            issued_at=self._now(),
            expires_at=issued.expires_at,
        )
        save_credential(self._settings.credential_path, self._credential)
