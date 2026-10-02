"""A host's life as a client of the gateway. It probes, then enrolls once
with its tenant's enrollment token, or picks up the credential it already
holds. From then on it beats, rotates its credential at half its life, and
claims: what it is handed is held to its owner's ceilings, and only then
given to the executor. Every connection is opened from here, outward.

What runs an item is the executor's (`ExecutorInterface`): the relay of a
tool call into a workspace, its output, and its result. Until one is
wired, `ExecutorPendingImpl` runs nothing, and the item's lease runs out
for the platform's sweep to take back."""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from acme.apps.host.ceilings import Ask, Ceilings, ask_of, refusals
from acme.apps.host.config import Credential, Settings, load_credential, save_credential
from acme.apps.host.probe import Probed, Probes, startup
from acme.client.client import ApiClient, ApiError
from acme.client.types import ClaimedWorkView, IsolationMode, IssuedHostCredentialView

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


class ExecutorPendingImpl(ExecutorInterface):
    """No executor yet: the item is logged and left to its lease."""

    async def run(self, item: ClaimedWorkView, ask: Ask) -> None:
        log.warning("item %s (%s) has no executor on this host yet", item.id, item.kind)


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
        else:
            await self._executor.run(answer.item, ask)
        return Handled(item=answer.item, refused=refused)

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
