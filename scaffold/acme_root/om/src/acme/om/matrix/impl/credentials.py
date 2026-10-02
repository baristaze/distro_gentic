"""The key each model call goes out on, by who pays the provider: the
platform's key for a tenant the platform bills, and the tenant's own live
key for a tenant on its own keys, read per call, so a rotated or refused
key never reaches one. Nothing that needs a tenant's key runs on the
platform's."""

import logging
from collections.abc import Callable
from uuid import UUID

from pydantic import ValidationError

from acme.integrations.model_providers.types import ProviderName
from acme.om.billing.storage import AccountStorageInterface
from acme.om.billing.types.account import FundingMode
from acme.om.context import TenantContext
from acme.om.exceptions import NoCredential, NotFound, SpenderUnknown, ValidationFailed
from acme.om.models.credentials import PLATFORM_CREDENTIAL, CallClient, CallCredentialsInterface
from acme.om.trust.keys import ProviderClientsInterface

log = logging.getLogger(__name__)


class CallCredentialsByFundingImpl(CallCredentialsInterface):
    """`platform` answers a call on the platform's key; `clients` serves the
    tenant's clients, one a live key, None in a process that builds none, so
    a tenant on its own keys gets no call there."""

    def __init__(
        self,
        platform: CallCredentialsInterface,
        accounts: AccountStorageInterface,
        clients: Callable[[], ProviderClientsInterface | None],
    ) -> None:
        self._platform = platform
        self._accounts = accounts
        self._clients = clients

    async def client_for(self, ctx: TenantContext, provider: ProviderName) -> CallClient:
        try:
            account = await self._accounts.read_account(ctx.org_id)
        except (ValidationFailed, ValidationError) as unread:
            log.error("the billing account of org %s cannot be read: %s", ctx.org_id, unread)
            raise SpenderUnknown(
                "the tenant's billing account cannot be read; nothing is spent"
            ) from unread
        if account is None or account.funding is not FundingMode.OWN_KEY:
            # The platform's key, which billing refuses for a tenant with no
            # account, as it refuses everything that tenant would spend.
            return await self._platform.client_for(ctx, provider)
        clients = self._clients()
        if clients is None:
            raise NoCredential(provider.value, "no client is built on a tenant's key here")
        try:
            keyed = await clients.client_for(ctx, provider)
        except NotFound as missing:
            raise NoCredential(
                provider.value,
                f"the tenant holds no live {provider.value} key, and pays its provider itself",
            ) from missing
        return CallClient(credential=str(keyed.reference), client=keyed.client)

    async def refused(self, ctx: TenantContext, provider: ProviderName, credential: str) -> None:
        if credential == PLATFORM_CREDENTIAL:
            await self._platform.refused(ctx, provider, credential)
            return
        clients = self._clients()
        try:
            reference = UUID(credential)
        except ValueError:
            log.error("%s refused a credential that names no key: %s", provider.value, credential)
            return
        if clients is not None:
            await clients.refuse(ctx, provider, reference)
