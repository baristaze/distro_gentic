"""A tenant's own provider keys, past the record: the probe that asks the
provider whether it takes a key before the key is saved, and the clients
built on a live key, cached by its reference."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from acme.integrations.model_providers import ModelProviderInterface
from acme.integrations.model_providers.types import ProviderName
from acme.om.context import TenantContext

ClientFactory = Callable[[ProviderName, str], ModelProviderInterface]
"""Builds a provider's client on a key's value. The value goes into the
client and nowhere else."""


@dataclass(frozen=True)
class TenantClient:
    """A client built on one of the tenant's keys, and that key's reference,
    which names it to the gate and the outage signal and never holds it."""

    reference: UUID
    client: ModelProviderInterface


class KeyProbeInterface(ABC):
    @abstractmethod
    async def probe(self, provider: ProviderName, value: str) -> None:
        """Asks the provider whether it takes the key, by a call that spends
        nothing. `KeyRefused` when it does not, and `Unavailable` when it
        cannot be asked; the key is saved only when this returns."""
        ...


class ProviderClientsInterface(ABC):
    @abstractmethod
    async def client_for(self, ctx: TenantContext, provider: ProviderName) -> TenantClient:
        """The tenant's client to `provider`, built on its live key and kept
        by the key's reference, with that reference. The live reference is
        read on every call and never cached, and a rotation mints a new one,
        so a client built on a rotated key is never served again. Serving a
        client marks the key used. `NotFound` when the tenant holds no live
        key for the provider."""
        ...

    @abstractmethod
    async def refuse(self, ctx: TenantContext, provider: ProviderName, reference: UUID) -> None:
        """The provider refused the tenant's key `reference` on a call: the
        key is marked refused, its value leaves the store, and its client is
        closed, so no call is offered it again and every session that needs
        it waits for a new one. A key no longer live changes nothing."""
        ...
