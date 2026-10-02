"""A host's life as a client of the gateway. It probes, then enrolls once
with its tenant's enrollment token, or picks up the credential it already
holds. From then on it beats, rotates its credential at half its life, and
claims: what it is handed is held to its owner's ceilings, and only then
given to the executor. Beside its claims it holds one long-lived control
stream open, which wakes it to claim at once and stops an item it runs at
once. Every connection is opened from here, outward.

What runs an item is the executor's (`ExecutorInterface`): the relay of a
tool call into a workspace, its output, and its result
(`relay.ExecutorRelayImpl`). `ExecutorPendingImpl` runs nothing, and the
item's lease runs out for the platform's sweep to take back."""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from acme.apps.host.ceilings import Ask, Ceilings, ask_of, refusals
from acme.apps.host.config import Credential, Settings, load_credential, save_credential
from acme.apps.host.probe import Probed, Probes, startup
from acme.client.client import ApiClient, ApiError
from acme.client.types import (
    ClaimedWorkView,
    ControlKind,
    IsolationMode,
    IssuedHostCredentialView,
)

log = logging.getLogger(__name__)

EXEC_VERSION = 1
"""The version of `exec` work this build of the host reads."""


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
    ) -> None:
        self._settings = settings
        self._ceilings = ceilings
        self._probes = probes
        self._client_for = client_for
        self._executor = executor or ExecutorPendingImpl()
        self._now = now
        self._probed: Probed | None = None
        self._credential: Credential | None = None
        self.woken = asyncio.Event()
        """Set when the control stream says work reached this host's lanes."""
        self._seen: UUID | None = None  # the last control message the host saw

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
        if not self.credential.due(self._now()):
            return False
        async with self._client_for(self.credential.token) as client:
            issued = await client.rotate_host_credential()
        self._keep(issued)
        return True

    async def claim_once(self) -> Handled | None:
        """One claim. The item is held to the owner's ceilings, and to what
        the host probed, before the executor sees it."""
        async with self._client_for(self.credential.token) as client:
            answer = await client.claim_host_work(EXEC_VERSION)
        if answer.item is None:
            return None
        ask = ask_of(answer.item)
        refused = refusals(self._ceilings, self._modes(), ask)
        if refused:
            log.warning("item %s refused: %s", answer.item.id, "; ".join(refused))
            await self._executor.refuse(answer.item, refused)
        else:
            await self._executor.run(answer.item, ask)
        return Handled(item=answer.item, refused=refused)

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
        try:
            await self.rotate_if_due()
            await self.beat()
            return await self.claim_once()
        except ApiError as error:
            log.warning("the platform refused: %s %s", error.code, error.message)
            raise

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
