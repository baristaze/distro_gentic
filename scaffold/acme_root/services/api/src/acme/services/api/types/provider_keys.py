"""Wire types of a tenant's own provider keys: the value a person saves,
which goes in and never comes back, and the record they see of each key."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, SecretStr

from acme.integrations.model_providers.types import ProviderName
from acme.om.trust.types.provider_key import KeyStatus
from acme.services.api.types.common import RequestBody, View

MAX_KEY = 4096
"""The longest key value a provider issues, with room to spare."""


class SaveKeyRequest(RequestBody):
    """A key's value. It is written once, under a new reference, and no
    response, log, or error ever carries it."""

    value: SecretStr = Field(min_length=1, max_length=MAX_KEY)


class ProviderKeyView(View):
    """What the tenant sees of a key: its reference, who added it and when,
    its state, and when it was last used. Never its value."""

    id: UUID
    provider: ProviderName
    status: KeyStatus
    created_at: datetime
    created_by: UUID
    last_used_at: datetime | None
