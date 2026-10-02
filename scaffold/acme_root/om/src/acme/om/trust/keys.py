"""A tenant's own provider keys, past the record: the probe that asks the
provider whether it takes a key before the key is saved, and the clients
built on a live key, cached by its reference."""

from abc import ABC, abstractmethod
from collections.abc import Callable

from acme.integrations.model_providers import ModelProviderInterface
from acme.integrations.model_providers.types import ProviderName
from acme.om.context import TenantContext

ClientFactory = Callable[[ProviderName, str], ModelProviderInterface]
"""Builds a provider's client on a key's value. The value goes into the
client and nowhere else."""


class KeyProbeInterface(ABC):
    @abstractmethod
    async def probe(self, provider: ProviderName, value: str) -> None:
        """Asks the provider whether it takes the key, by a call that spends
        nothing. `KeyRefused` when it does not, and `Unavailable` when it
        cannot be asked; the key is saved only when this returns."""
        ...


class ProviderClientsInterface(ABC):
    @abstractmethod
    async def client_for(
        self, ctx: TenantContext, provider: ProviderName
    ) -> ModelProviderInterface:
        """The tenant's client to `provider`, built on its live key and kept
        by the key's reference. The live reference is read on every call and
        never cached, and a rotation mints a new one, so a client built on a
        rotated key is never served again. Serving a client marks the key
        used. `NotFound` when the tenant holds no live key for the
        provider."""
        ...
