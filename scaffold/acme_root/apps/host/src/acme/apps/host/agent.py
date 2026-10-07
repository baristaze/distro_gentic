"""A host's life as a client of the gateway, on the claimant kit
(`acme.client.claimant`). It probes, then enrolls once with its tenant's
enrollment token, or picks up the credential it already holds, as every
claimant does, through the host's own calls. From then on it beats,
rotates its credential at half its life, and claims: what it is handed is held to its owner's ceilings, and only then
given to the executor, which runs it beside the others it runs, up to the
number its owner's ceilings allow. Beside its claims it holds one long-lived control
stream open, which wakes it to claim at once and stops an item it runs at
once. Every connection is opened from here, outward.

What runs an item is the executor's (`ExecutorInterface`): the relay of a
tool call into a workspace, its output, and its result
(`relay.ExecutorRelayImpl`). `ExecutorPendingImpl` runs nothing, and the
item's lease runs out for the platform's sweep to take back."""

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from acme.apps.host.ceilings import Ask, Ceilings, ask_of, refusals
from acme.apps.host.config import Settings
from acme.apps.host.probe import Probed, Probes, startup
from acme.client.claimant.backoff import Backoff
from acme.client.claimant.credential import Credential
from acme.client.claimant.enrollment import (
    REFUSED,
    ClientFactory,
    Enrollment,
    Issued,
    RoutesInterface,
    refused,
)
from acme.client.client import WIRE_FAILURES, ApiClient, ApiError
from acme.client.types import (
    AdvertisementBody,
    ClaimedWorkView,
    ControlKind,
    IsolationMode,
    IssuedHostCredentialView,
)

log = logging.getLogger(__name__)

EXEC_VERSION = 1
"""The version of `exec` work this build of the host reads."""

ENDS_THE_HOST = REFUSED | {426}
"""The answers a host does not outlast: its credential refused, ended, or
revoked, and the work it reads below the floor. Every other failure, an
answer the API could not serve, a 429, or the wire, the host waits out
(`Backoff`) and calls again with the credential it holds."""


def host_issued(view: IssuedHostCredentialView) -> Issued:
    return Issued(
        token=view.token,
        credential_id=view.credential_id,
        claimant_id=view.host_id,
        pool_id=view.pool_id,
        expires_at=view.expires_at,
    )


class RoutesHostImpl(RoutesInterface):
    """The host's own enrollment, with what it probed and the version of
    `exec` work it reads, at `/hosts/...`."""

    def __init__(self, advertisement: Callable[[], AdvertisementBody]) -> None:
        self._advertisement = advertisement

    async def enroll(self, client: ApiClient, enrollment_token: str, name: str) -> Issued:
        issued = await client.enroll_host(
            enrollment_token, name, self._advertisement(), EXEC_VERSION
        )
        return host_issued(issued)

    async def rotate(self, client: ApiClient) -> Issued:
        return host_issued(await client.rotate_host_credential())


class ExecutorInterface(ABC):
    @abstractmethod
    async def run(self, item: ClaimedWorkView, ask: Ask) -> None:
        """Runs an item the ceilings let through, at no more than it asked."""
        ...

    @abstractmethod
    async def refuse(self, item: ClaimedWorkView, reasons: list[str]) -> None:
        """Answers an item the ceilings refused, before anything ran, so the
        run that sent it reads why."""
        ...

    @abstractmethod
    def stop(self, item_id: UUID, kind: str) -> bool:
        """Ends an item that runs here, at once, as the control stream says;
        whether one did."""
        ...


class ExecutorPendingImpl(ExecutorInterface):
    """No executor yet: the item is logged and left to its lease."""

    async def run(self, item: ClaimedWorkView, ask: Ask) -> None:
        log.warning("item %s (%s) has no executor on this host yet", item.id, item.kind)

    async def refuse(self, item: ClaimedWorkView, reasons: list[str]) -> None:
        return None

    def stop(self, item_id: UUID, kind: str) -> bool:
        return False


@dataclass(frozen=True)
class Handled:
    """What became of one claimed item."""

    item: ClaimedWorkView
    refused: list[str]


class HostAgent:
    def __init__(
        self,
        settings: Settings,
        ceilings: Ceilings,
        probes: Probes,
        client_for: ClientFactory,
        executor: ExecutorInterface | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._settings = settings
        self._ceilings = ceilings
        self._probes = probes
        self._client_for = client_for
        self._executor = executor or ExecutorPendingImpl()
        self._now = now
        self._backoff = Backoff(jitter)
        self._probed: Probed | None = None
        self._enrollment = Enrollment(
            settings, RoutesHostImpl(lambda: self.probed.advertisement), client_for, now
        )
        self.woken = asyncio.Event()
        """Set when the control stream says work reached this host's lanes."""
        self._seen: UUID | None = None  # the last control message the host saw
        self._running: set[asyncio.Task[None]] = set()

    @property
    def probed(self) -> Probed:
        if self._probed is None:
            raise RuntimeError("the host has not started")
        return self._probed

    @property
    def credential(self) -> Credential:
        return self._enrollment.credential

    async def start(self) -> None:
        """Probes, then enrolls or resumes. A failed probe raises
        `Misconfigured` before anything is sent with a credential."""
        async with self._client_for(None) as client:
            self._probed = await startup(
                self._probes, client, self._settings.max_clock_skew_seconds, self._now
            )
        if not self._probed.open_egress:
            reached = next(r for r in self._probed.results if r.name == "metadata")
            log.warning("open egress is refused here: %s", reached.detail)
        if await self._enrollment.start():
            await self.beat()

    async def beat(self) -> None:
        async with self.client() as client:
            await client.host_heartbeat(self.probed.advertisement, EXEC_VERSION)

    async def rotate_if_due(self) -> bool:
        """Rotates once when due, one rotation at a time, so a loop that
        beats beside the claims never rotates with the one a turn just
        rotated (`Enrollment.rotate_if_due`)."""
        return await self._enrollment.rotate_if_due()

    async def claim_once(self) -> Handled | None:
        """One claim, while the host runs fewer items than its ceilings allow:
        none is claimed past that, so no lease is held for work that waits.
        The item is held to the owner's ceilings, and to what the host
        probed, before the executor sees it. It runs beside the others; when
        it ends, `woken` is set, so the loop claims again at once."""
        if len(self._running) >= self._ceilings.items_at_once:
            return None
        async with self.client() as client:
            answer = await client.claim_host_work(EXEC_VERSION)
        if answer.item is None:
            return None
        ask = ask_of(answer.item)
        refused = refusals(self._ceilings, self._modes(), ask, open_egress=self.probed.open_egress)
        if refused:
            log.warning("item %s refused: %s", answer.item.id, "; ".join(refused))
            await self._executor.refuse(answer.item, refused)
        else:
            task = asyncio.ensure_future(self._run(answer.item, ask))
            self._running.add(task)
            task.add_done_callback(self._ended)
        return Handled(item=answer.item, refused=refused)

    async def idle(self) -> None:
        """Waits until no item runs here."""
        while self._running:
            await asyncio.wait(set(self._running))

    async def _run(self, item: ClaimedWorkView, ask: Ask) -> None:
        try:
            await self._executor.run(item, ask)
        except Exception:
            # Its lease runs out, and the platform's sweep settles it.
            log.exception("item %s failed on this host", item.id)

    def _ended(self, task: asyncio.Task[None]) -> None:
        self._running.discard(task)
        self.woken.set()

    def client(self) -> ApiClient:
        """A client that calls with this host's credential as it is now;
        none once the platform refused it."""
        return self._enrollment.client()

    async def listen(self) -> None:
        """The control stream, held open from here until the platform ends
        it with the credential it was opened with: a wake sets `woken`, and
        a stop ends the item it names at once. The last message seen is
        where the next stream starts."""
        async with self.client() as client:
            async for message in client.control_stream(self._seen):
                if message.id is not None:
                    self._seen = message.id
                if message.kind is ControlKind.wake:
                    self.woken.set()
                elif message.item_id is not None and self._executor.stop(
                    message.item_id, message.kind.value
                ):
                    log.info("item %s stopped: %s", message.item_id, message.kind.value)

    async def tick(self) -> Handled | None:
        """One turn of the host's loop: rotate when due, beat, claim."""
        await self.rotate_if_due()
        await self.beat()
        return await self.claim_once()

    async def turn(self) -> float:
        """One turn, and how long to wait before the next: none while there
        is work, a beat when there is none, and a growing wait after a
        failure the host outlasts, with the credential it holds. A refusal
        in `ENDS_THE_HOST` is raised, and ends the host."""
        try:
            handled = await self.tick()
        except ApiError as error:
            if error.status in ENDS_THE_HOST:
                log.warning("the platform refused: %s %s", error.code, error.message)
                if refused(error):
                    self._enrollment.refuse()
                raise
            log.warning("the platform failed: %s %s", error.status, error.code)
            return self._backoff.failed(error.retry_after)
        except WIRE_FAILURES as error:
            log.warning("the platform is unreachable: %s", error)
            return self._backoff.failed(None)
        self._backoff.reset()
        return 0.0 if handled is not None else self._settings.beat_seconds

    def _modes(self) -> frozenset[IsolationMode]:
        return frozenset(self.probed.advertisement.isolation_modes or ())
