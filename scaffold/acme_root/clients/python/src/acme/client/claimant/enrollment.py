"""A claimant's credential through its life. It enrolls once with its
tenant's enrollment token, or picks up the live credential it already
holds for the same platform. From then on it rotates the credential at
half its life, one rotation at a time, and keeps each one owner-only on
its disk before it calls with it. A credential the platform refused is
never sent again: every call after it raises `CredentialRefused`.

The calls that enroll and rotate are its kind's (`RoutesInterface`): a
product's claimant's are `/claimants/...` (`ClaimantRoutes`); the host's
carry what it probed."""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from acme.client.claimant.credential import Credential, load_credential, save_credential
from acme.client.claimant.settings import ClaimantSettings
from acme.client.client import ApiClient, ApiError
from acme.client.types import IssuedClaimantCredentialView

log = logging.getLogger(__name__)

REFUSED = frozenset({401, 403})
"""The answers that refuse the credential itself: refused, ended, or
revoked. A claimant does not outlast them."""


class NotEnrolled(RuntimeError):
    """The claimant holds no live credential and was given no enrollment
    token: its owner issues one, and the claimant is started with it once."""


class CredentialRefused(RuntimeError):
    """The platform refused the claimant's credential: it stops, and sends
    the credential no more."""


def refused(error: BaseException) -> bool:
    """Whether a failure refuses the credential."""
    return isinstance(error, ApiError) and error.status in REFUSED


@dataclass(frozen=True)
class Issued:
    """What an enrollment or a rotation answers, whatever the kind's calls."""

    token: str | None
    credential_id: UUID
    claimant_id: UUID
    pool_id: UUID
    expires_at: datetime


ClientFactory = Callable[[str | None], ApiClient]
"""Builds the client for a bearer: the claimant's credential, or None."""


class RoutesInterface(ABC):
    """How a kind enrolls and rotates its credential."""

    @abstractmethod
    async def enroll(self, client: ApiClient, enrollment_token: str, name: str) -> Issued: ...

    @abstractmethod
    async def rotate(self, client: ApiClient) -> Issued: ...


def claimant_issued(view: IssuedClaimantCredentialView) -> Issued:
    return Issued(
        token=view.token,
        credential_id=view.credential_id,
        claimant_id=view.claimant_id,
        pool_id=view.pool_id,
        expires_at=view.expires_at,
    )


class ClaimantRoutes(RoutesInterface):
    """A product's claimant's calls: its name alone, beside its token."""

    async def enroll(self, client: ApiClient, enrollment_token: str, name: str) -> Issued:
        return claimant_issued(await client.enroll_claimant(enrollment_token, name))

    async def rotate(self, client: ApiClient) -> Issued:
        return claimant_issued(await client.rotate_claimant_credential())


class Enrollment:
    def __init__(
        self,
        settings: ClaimantSettings,
        routes: RoutesInterface,
        client_for: ClientFactory,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._routes = routes
        self._client_for = client_for
        self._now = now
        self._credential: Credential | None = None
        self._rotating = asyncio.Lock()
        self._refused = False

    @property
    def credential(self) -> Credential:
        if self._credential is None:
            raise RuntimeError("the claimant has not started")
        return self._credential

    @property
    def refused(self) -> bool:
        return self._refused

    async def start(self) -> bool:
        """Picks up the live credential held for this platform, and says
        True; or enrolls once with the enrollment token, and says False."""
        held = load_credential(self._settings.credential_path)
        if (
            held is not None
            and held.api_url == self._settings.api_url
            and not held.ended(self._now())
        ):
            self._credential = held
            return True
        token = self._settings.enrollment_token
        if not token:
            raise NotEnrolled("no live credential and no enrollment token to enroll with")
        async with self._client_for(None) as client:
            issued = await self._routes.enroll(client, token, self._settings.name)
        self._keep(issued)
        log.info("enrolled as %s of pool %s", issued.claimant_id, issued.pool_id)
        return False

    async def rotate_if_due(self) -> bool:
        """Rotates once when due. One rotation at a time: a credential
        rotated a second time ends the claimant, so two loops that both
        find it due never rotate the same one twice."""
        async with self._rotating:
            if not self.credential.due(self._now()):
                return False
            try:
                async with self.client() as client:
                    issued = await self._routes.rotate(client)
            except ApiError as error:
                if refused(error):
                    self.refuse()
                raise
            self._keep(issued)
            return True

    def client(self) -> ApiClient:
        """A client that calls with the credential as it is now. Once the
        credential is refused, none is built."""
        if self._refused:
            raise CredentialRefused("the platform refused this claimant's credential")
        return self._client_for(self.credential.token)

    def refuse(self) -> None:
        """The platform refused the credential: no call carries it again."""
        if not self._refused:
            log.warning("the platform refused this claimant's credential")
        self._refused = True

    def _keep(self, issued: Issued) -> None:
        """Kept on the disk before anything calls with it, so a claimant
        stopped at once still holds the credential the platform last issued."""
        if issued.token is None:
            raise NotEnrolled("the platform answered no credential")
        credential = Credential(
            api_url=self._settings.api_url,
            token=issued.token,
            credential_id=str(issued.credential_id),
            claimant_id=str(issued.claimant_id),
            pool_id=str(issued.pool_id),
            issued_at=self._now(),
            expires_at=issued.expires_at,
        )
        save_credential(self._settings.credential_path, credential)
        self._credential = credential
