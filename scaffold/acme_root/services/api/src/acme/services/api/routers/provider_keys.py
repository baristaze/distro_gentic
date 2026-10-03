"""A tenant's own keys to its model providers. A key's value goes in and
never comes back: the routes answer the record alone, who added the key,
when, its state, and when it was last used. A key is probed before it is
saved, and one the provider refuses is not saved. Saving mints a new
reference and makes it the live key, so the write is a PUT, and a retry
lands the same live value: it takes no Idempotency-Key."""

from fastapi import APIRouter

from acme.integrations.model_providers.types import ProviderName
from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.resolve import ProviderKeysService
from acme.services.api.types.common import LIMIT_DEFAULT
from acme.services.api.types.provider_keys import ProviderKeyView, SaveKeyRequest

router = APIRouter(prefix="/provider-keys", tags=["provider-keys"])


@router.get("", response_model=list[ProviderKeyView])
async def get_keys(
    ctx: Ctx, service: ProviderKeysService, limit: int = LIMIT_DEFAULT
) -> list[ProviderKeyView]:
    """The tenant's keys, the newest first, a rotated or refused one among
    them; never a value."""
    return await service.get_keys(ctx, limit)


@router.put("/{provider}", response_model=ProviderKeyView)
async def save_key(
    ctx: Ctx, service: ProviderKeysService, provider: ProviderName, body: SaveKeyRequest
) -> ProviderKeyView:
    """The tenant's live key to `provider`, the one before it rotated out.
    Requires managing the org. `key_refused` when the provider does not take
    it, and 503 when no probe can ask."""
    return await service.save_key(ctx, provider, body)
