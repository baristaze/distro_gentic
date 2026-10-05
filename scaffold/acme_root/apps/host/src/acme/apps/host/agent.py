"""A host's life as a client of the gateway. It probes, then enrolls once
with its tenant's enrollment token, or picks up the credential it already
holds. From then on it beats, rotates its credential at half its life, and
claims: what it is handed is held to its owner's ceilings, and only then
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
from acme.apps.host.config import Credential, Settings, load_credential, save_credential
from acme.apps.host.probe import Probed, Probes, startup
from acme.client.client import WIRE_FAILURES, ApiClient, ApiError
from acme.client.types import (
    ClaimedWorkView,
    ControlKind,
    IsolationMode,
    IssuedHostCredentialView,
)

log = logging.getLogger(__name__)

EXEC_VERSION = 1
"""The version of `exec` work this build of the host reads."""

ENDS_THE_HOST = frozenset({401, 403, 426})
"""The answers a host does not outlast: its credential refused, ended, or
revoked, and the work it reads below the floor. Every other failure, an
answer the API could not serve, a 429, or the wire, the host waits out and
calls again with the credential it holds."""

BACKOFF_FIRST_SECONDS = 1.0
"""The wait after a first failure. It doubles per failure in a row."""

BACKOFF_MAX_SECONDS = 120.0
"""However many failures in a row, no wait is longer, a 429's ask included."""


class NotEnrolled(RuntimeError):
    """The host holds no live credential and was given no enrollment token:
    its owner issues one, and the host is started with it once."""


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


ClientFactory = Callable[[str | None], ApiClient]
"""Builds the client for a bearer: the host's credential, or None."""


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
        self._jitter = jitter
        self._failures = 0
        self._probed: Probed | None = None
        self._credential: Credential | None = None
        self.woken = asyncio.Event()
        """Set when the control stream says work reached this host's lanes."""
        self._seen: UUID | None = None  # the last control message the host saw
        self._rotating = asyncio.Lock()
        self._running: set[asyncio.Task[None]] = set()

    @property
    def probed(self) -> Probed:
        if self._probed is None:
            raise RuntimeError("the host has not started")
        return self._probed

    @property
    def credential(self) -> Credential:
        if self._credential is None:
            raise RuntimeError("the host has not started")
        return self._credential

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
        held = load_credential(self._settings.credential_path)
        if (
            held is not None
            and held.api_url == self._settings.api_url
            and not held.ended(self._now())
        ):
            self._credential = held
            await self.beat()
            return
        token = self._settings.enrollment_token
        if not token:
            raise NotEnrolled("no live credential and no ACME_ENROLLMENT_TOKEN to enroll with")
        async with self._client_for(None) as client:
            issued = await client.enroll_host(
                token, self._settings.name, self.probed.advertisement, EXEC_VERSION
            )
        self._keep(issued)
        log.info("enrolled as host %s of pool %s", issued.host_id, issued.pool_id)

    async def beat(self) -> None:
        async with self._client_for(self.credential.token) as client:
            await client.host_heartbeat(self.probed.advertisement, EXEC_VERSION)

    async def rotate_if_due(self) -> bool:
        """Rotates once when due. One rotation at a time: a credential
        rotated a second time ends the host, so a loop that beats beside the
        claims never rotates with the one a turn just rotated."""
        async with self._rotating:
            if not self.credential.due(self._now()):
                return False
            async with self._client_for(self.credential.token) as client:
                issued = await client.rotate_host_credential()
            self._keep(issued)
            return True

    async def claim_once(self) -> Handled | None:
        """One claim, while the host runs fewer items than its ceilings allow:
        none is claimed past that, so no lease is held for work that waits.
        The item is held to the owner's ceilings, and to what the host
        probed, before the executor sees it. It runs beside the others; when
        it ends, `woken` is set, so the loop claims again at once."""
        if len(self._running) >= self._ceilings.items_at_once:
            return None
        async with self._client_for(self.credential.token) as client:
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
        """A client that calls with this host's credential as it is now."""
        return self._client_for(self.credential.token)

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
                raise
            log.warning("the platform failed: %s %s", error.status, error.code)
            return self._backoff(error.retry_after)
        except WIRE_FAILURES as error:
            log.warning("the platform is unreachable: %s", error)
            return self._backoff(None)
        self._failures = 0
        return 0.0 if handled is not None else self._settings.beat_seconds

    def _backoff(self, server_asked: float | None) -> float:
        """The wait after one more failure in a row: the doubling curve, half
        of it jitter so hosts that failed together do not return together,
        or longer when the server asked, and never past the cap."""
        self._failures += 1
        full = min(BACKOFF_FIRST_SECONDS * 2 ** (self._failures - 1), BACKOFF_MAX_SECONDS)
        curve = full / 2 + (full / 2) * self._jitter()
        return min(max(curve, server_asked or 0.0), BACKOFF_MAX_SECONDS)

    def _modes(self) -> frozenset[IsolationMode]:
        return frozenset(self.probed.advertisement.isolation_modes or ())

    def _keep(self, issued: IssuedHostCredentialView) -> None:
        if issued.token is None:
            raise NotEnrolled("the platform answered no credential")
        self._credential = Credential(
            api_url=self._settings.api_url,
            token=issued.token,
            credential_id=str(issued.credential_id),
            host_id=str(issued.host_id),
            pool_id=str(issued.pool_id),
            issued_at=self._now(),
            expires_at=issued.expires_at,
        )
        save_credential(self._settings.credential_path, self._credential)
