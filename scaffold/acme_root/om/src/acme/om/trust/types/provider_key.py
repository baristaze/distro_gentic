"""A tenant's own key to a model provider, by reference. The record is the
reference: its id names the key's value in the secret store, and a
rotation mints a new record, so a reference names one value for its whole
life. A client cached by reference therefore never serves a rotated key.

The record holds who added the key, when, and when it was last used, and
never the value: what the tenant sees of its key is this record."""

from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import Field

from acme.integrations.model_providers.types import ProviderName
from acme.om.base import Identifiable, Trackable


class KeyStatus(StrEnum):
    LIVE = "live"  # the one key that serves the tenant's calls to its provider
    ROTATED = "rotated"  # a newer reference replaced it, and its value left the store
    REFUSED = "refused"  # the provider refused it; the calls that need it wait for a new one


class ProviderKey(Identifiable, Trackable):
    """The id is the reference. `created_by` is who added the key and
    `created_at` when; `last_used_at` is when a client was last served from
    it, to the granularity the manager's options set."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = ("status", "last_used_at", "version")

    provider: ProviderName
    status: KeyStatus = KeyStatus.LIVE
    last_used_at: datetime | None = None
    # Every write after the create is a compare-and-set on it.
    version: int = Field(default=1, ge=1)


def key_secret_name(reference: UUID) -> str:
    """The name the secret store keeps a key's value under: its reference,
    so a rotated key's name is never reused."""
    return f"provider-key-{reference.hex}"
