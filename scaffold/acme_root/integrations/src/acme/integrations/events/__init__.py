"""The integrations whose events reach a session, and through which the
platform tells a person what waits on them: a forge's comments, checks,
pushes, and tickets, a chat's messages. The forge also takes a session's
branch and opens its pull request, with the integration's own credential,
which never leaves it. One interface for each, a real
client or a twin, and a caller never knows which it holds.

An integration checks the signature of each delivery its system sends and
reads it into the platform's terms (`ProvidedEvent`). It also checks the
grant its system hands a person who installs the platform there, and
answers the installation the grant names: the system's word for which
installation a tenant connects, never the person's. What served it is the
integration's own word (`provenance`), never the delivery's: a twin's
event is a twin's whatever its body says. Nothing here imports the object
model; the ingress maps an event into the router's shape."""

import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from acme.integrations.exceptions import ProviderUnavailable

Provenance = Literal["real", "twin"]
"""What served a record: the system itself, or its twin."""

DELIVERY_NAMESPACE = uuid.UUID("0b6f1f5e-3c55-4a61-9a2e-6f2d8f6c4e17")
"""The namespace of a delivery's key: one integration's delivery is one key."""

INTEGRATIONS: tuple[str, ...] = ("forge", "chat")
"""The integrations the platform names: the forge that holds a session's
work (its pull requests, branches, checks, and tickets), and the chat its
people talk in."""


def delivery_key(integration: str, delivery_id: str) -> uuid.UUID:
    """A delivery's key: a UUID v5 over the integration and its id for the
    delivery, so a retried delivery carries the same key."""
    return uuid.uuid5(DELIVERY_NAMESPACE, f"{integration}:{delivery_id}")


class ProvidedEvent(BaseModel):
    """One delivery, read: its key and the integration's id for it; the
    installation it came through, the system's own id, which the tenant
    that connected it is found by; and the event in the platform's terms,
    which the router validates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: uuid.UUID
    delivery_id: str
    installation: str
    arrival: str
    author_kind: str
    author_id: str
    author_name: str
    session_id: str | None = None
    pull_request: str | None = None
    branch: str | None = None
    refs: tuple[str, ...] = ()
    text: str = ""
    check: str | None = None
    occurred_at: datetime


class PostedMessage(BaseModel):
    """A message the platform posted to an address of the integration, as the
    integration recorded it, with what served it, and the mark it carries
    when the platform named the act."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    address: str
    text: str
    provenance: Provenance
    posted_at: datetime
    mark: str | None = None


class OpenedPullRequest(BaseModel):
    """A pull request the platform opened through the integration, as the
    integration recorded it, with what served it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    url: str
    repository: str
    head: str
    base: str | None
    title: str
    body: str
    provenance: Provenance


class IntegrationInterface(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """The integration's name, as the platform's records carry it."""
        ...

    @property
    @abstractmethod
    def provenance(self) -> Provenance:
        """What serves this integration: `twin` for a twin, whatever a
        delivery says."""
        ...

    @abstractmethod
    def verify_delivery(
        self, payload: bytes, headers: Mapping[str, str], now: datetime
    ) -> ProvidedEvent:
        """The event a delivery carries, once its signature over the body and
        its timestamp checks out at `now`; `DeliveryRefused` otherwise, naming
        what failed and never the secret. `headers` are the delivery's, their
        names in lower case."""
        ...

    @abstractmethod
    async def verify_installation(self, grant: str, now: datetime) -> str:
        """The installation a grant names, once the system confirms it at
        `now`: the grant the system hands the person who installed the
        platform there. The system's scheme confirms it: its signature over
        the grant, or a call to the system when the grant is a code or an
        unsigned id, and never the id alone. `DeliveryRefused` when the grant
        fails, naming what failed and never the secret; `ProviderUnavailable`
        when the system cannot be asked."""
        ...

    @abstractmethod
    async def post(self, address: str, text: str, mark: str | None = None) -> PostedMessage:
        """Posts `text` to an address of the integration, such as a person's
        chat account or a pull request; `ProviderUnavailable` when it cannot.
        `mark` is the platform's name for the act: the system carries it on
        what it makes, so every delivery of or after it names it among its
        refs."""
        ...

    @abstractmethod
    async def push_branch(self, repository: str, branch: str, head: str) -> None:
        """Points `branch` of `repository` at the commit `head`, with the
        integration's own credential. `ProviderRefused` from an integration
        that holds no repository; `ProviderUnavailable` when it cannot."""
        ...

    @abstractmethod
    async def open_pull_request(
        self, repository: str, head: str, base: str | None, title: str, body: str
    ) -> OpenedPullRequest:
        """Opens the pull request of branch `head` onto `base`, the
        repository's default branch when None, or answers the one of `head`
        open already, so a repeated call opens no second. Refused and
        unavailable as `push_branch` is."""
        ...

    @abstractmethod
    def describe(self) -> str:
        """One line for the boot log."""
        ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...


class IntegrationAbsentImpl(IntegrationInterface):
    """An integration this process has none of: every delivery and every post
    is refused as unavailable."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def provenance(self) -> Provenance:
        return "real"

    def verify_delivery(
        self, payload: bytes, headers: Mapping[str, str], now: datetime
    ) -> ProvidedEvent:
        raise ProviderUnavailable(f"no {self._name} integration is configured")

    async def verify_installation(self, grant: str, now: datetime) -> str:
        raise ProviderUnavailable(f"no {self._name} integration is configured")

    async def post(self, address: str, text: str, mark: str | None = None) -> PostedMessage:
        raise ProviderUnavailable(f"no {self._name} integration is configured")

    async def push_branch(self, repository: str, branch: str, head: str) -> None:
        raise ProviderUnavailable(f"no {self._name} integration is configured")

    async def open_pull_request(
        self, repository: str, head: str, base: str | None, title: str, body: str
    ) -> OpenedPullRequest:
        raise ProviderUnavailable(f"no {self._name} integration is configured")

    def describe(self) -> str:
        return f"{self._name}=none"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None
