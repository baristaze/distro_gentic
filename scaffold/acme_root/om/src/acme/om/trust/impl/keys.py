import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from acme.infra.secrets import SecretsInterface
from acme.integrations.model_providers import ModelProviderInterface
from acme.integrations.model_providers.types import ProviderName
from acme.om.base import utcnow
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import NotFound, Unavailable
from acme.om.trust.exceptions import KeyRefused
from acme.om.trust.keys import (
    ClientFactory,
    KeyProbeInterface,
    ProviderClientsInterface,
    TenantClient,
)
from acme.om.trust.rules import used_since
from acme.om.trust.storage import TrustStorageInterface
from acme.om.trust.types.provider_key import KeyStatus, key_secret_name

log = logging.getLogger(__name__)


class KeyProbeAbsentImpl(KeyProbeInterface):
    """A process with no probe: no key can be asked about, so none is saved.
    A loud null: it refuses every probe, and never lets a key through
    unasked."""

    async def probe(self, provider: ProviderName, value: str) -> None:
        raise Unavailable(f"no probe of {provider.value} keys is configured, so no key is saved")


class KeyProbeTwinImpl(KeyProbeInterface):
    """The probe's twin: it takes every key but those it is told the provider
    refuses, and remembers which providers it was asked about, never a
    value."""

    def __init__(self, refused: frozenset[str] = frozenset()) -> None:
        self._refused = refused
        self.asked: list[ProviderName] = []

    async def probe(self, provider: ProviderName, value: str) -> None:
        self.asked.append(provider)
        if value in self._refused:
            raise KeyRefused(f"{provider.value} refused the key")


class ProviderClientsCachedImpl(ProviderClientsInterface):
    """A client a key, kept in this process by the key's reference. The live
    reference is read from storage on every call, so another process's
    rotation reaches this one at its next call; the client of a reference
    that is no longer live is dropped and closed when the live one is seen."""

    def __init__(
        self,
        storage: TrustStorageInterface,
        secrets: SecretsInterface,
        factory: ClientFactory,
        *,
        use_grain: timedelta,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        """`use_grain` is how often a key's use is written: its record says
        when it was last used to this grain, and a call costs no write."""
        self._storage = storage
        self._secrets = secrets
        self._factory = factory
        self._use_grain = use_grain
        self._clock = clock
        self._clients: dict[UUID, ModelProviderInterface] = {}
        self._live: dict[tuple[UUID, ProviderName], UUID] = {}

    async def client_for(self, ctx: TenantContext, provider: ProviderName) -> TenantClient:
        ctx.require(Permission.WRITE)
        key = await self._storage.read_live_key(ctx.org_id, provider)
        if key is None:
            raise NotFound(f"the tenant holds no live {provider.value} key")
        held = self._live.get((ctx.org_id, provider))
        if held is not None and held != key.id:
            # Rotated: the client of the old reference is never served again.
            stale = self._clients.pop(held, None)
            if stale is not None:
                await stale.close()
        self._live[(ctx.org_id, provider)] = key.id
        client = self._clients.get(key.id)
        if client is None:
            value = await self._secrets.get(
                ctx.org_id, key_secret_name(key.id), deadline=ctx.deadline
            )
            client = self._factory(provider, value)
            self._clients[key.id] = client
        now = self._clock()
        if used_since(key.last_used_at, now, self._use_grain):
            await self._storage.touch_key(ctx.org_id, key.id, now)
        return TenantClient(reference=key.id, client=client)

    async def refuse(self, ctx: TenantContext, provider: ProviderName, reference: UUID) -> None:
        ctx.require(Permission.WRITE)
        key = await self._storage.read_live_key(ctx.org_id, provider)
        if key is None or key.id != reference:
            return
        refused = key.model_copy(
            update={
                "status": KeyStatus.REFUSED,
                "version": key.version + 1,
                "updated_at": self._clock(),
                "updated_by": ctx.user_id,
            }
        )
        if not await self._storage.refuse_key(ctx.org_id, refused):
            return
        log.warning("%s refused the key %s of org %s", provider.value, key.id, ctx.org_id)
        # Its value leaves the store and its client closes: nothing can
        # offer it to a call again.
        await self._secrets.delete(ctx.org_id, key_secret_name(key.id), deadline=ctx.deadline)
        if self._live.get((ctx.org_id, provider)) == key.id:
            del self._live[(ctx.org_id, provider)]
        stale = self._clients.pop(key.id, None)
        if stale is not None:
            await stale.close()
