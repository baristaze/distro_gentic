from acme.integrations.model_providers.types import ProviderName
from acme.om.context import TenantContext
from acme.om.trust import TrustManagerInterface
from acme.services.api.services.provider_keys import ProviderKeysServiceInterface
from acme.services.api.types.common import clamp_limit
from acme.services.api.types.provider_keys import ProviderKeyView, SaveKeyRequest


class ProviderKeysServiceImpl(ProviderKeysServiceInterface):
    def __init__(self, trust: TrustManagerInterface) -> None:
        self._trust = trust

    async def save_key(
        self, ctx: TenantContext, provider: ProviderName, body: SaveKeyRequest
    ) -> ProviderKeyView:
        # The value leaves its wrapper here, for the manager alone, which
        # probes it and writes it to the secret store.
        saved = await self._trust.save_provider_key(ctx, provider, body.value.get_secret_value())
        return ProviderKeyView.model_validate(saved)

    async def get_keys(self, ctx: TenantContext, limit: int) -> list[ProviderKeyView]:
        keys = await self._trust.get_provider_keys(ctx, clamp_limit(limit))
        return [ProviderKeyView.model_validate(key) for key in keys]
