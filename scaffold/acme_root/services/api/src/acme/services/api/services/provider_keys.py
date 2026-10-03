"""The provider keys service: a tenant saves its own key to a provider, and
reads the record of each key, never a value."""

from abc import ABC, abstractmethod

from acme.integrations.model_providers.types import ProviderName
from acme.om.context import TenantContext
from acme.services.api.types.provider_keys import ProviderKeyView, SaveKeyRequest


class ProviderKeysServiceInterface(ABC):
    @abstractmethod
    async def save_key(
        self, ctx: TenantContext, provider: ProviderName, body: SaveKeyRequest
    ) -> ProviderKeyView:
        """The key saved, probed first, as the live key to `provider`: its
        record, which never holds the value. `KeyRefused` when the provider
        does not take it, and `Unavailable` when no probe can ask."""
        ...

    @abstractmethod
    async def get_keys(self, ctx: TenantContext, limit: int) -> list[ProviderKeyView]:
        """The tenant's keys, the newest first: who added each, when, its
        state, and when it was last used."""
        ...
