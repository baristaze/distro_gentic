"""The integrations whose events reach a session, and through which the
platform tells a person what waits on them: a forge's comments, checks,
pushes, and tickets, a chat's messages. One interface for each, a real
client or a twin, and a caller never knows which it holds.

An integration checks the signature of each delivery its system sends and
reads it into the platform's terms (`ProvidedEvent`). What served it is the
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
    installation it came through, which names the tenant; and the event in
    the platform's terms, which the router validates."""

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
    integration recorded it, with what served it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    address: str
    text: str
    provenance: Provenance
    posted_at: datetime


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
    async def post(self, address: str, text: str) -> PostedMessage:
        """Posts `text` to an address of the integration, such as a person's
        chat account; `ProviderUnavailable` when it cannot."""
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

    async def post(self, address: str, text: str) -> PostedMessage:
        raise ProviderUnavailable(f"no {self._name} integration is configured")

    def describe(self) -> str:
        return f"{self._name}=none"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None
