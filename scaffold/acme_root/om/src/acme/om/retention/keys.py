"""Whose key service holds a tenant's keys, and what it says when it destroys
one.

The engine seals each session's content under a key of its own, wrapped by
the tenant's key service (`acme.om.privacy`). The platform adds two things.
A tenant may bring its own key service, which then wraps and unwraps every
key of that tenant and nothing of any other. And a key service that holds
each session's key, not only the tenant's, can destroy one: from then on no
wrapped copy of it opens anywhere, and the service reports the destruction
in its own words, which the audit keeps as they came."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.infra.keys import KeyServiceInterface
from acme.om.base import Platform


class KeyDestruction(Platform):
    """A session's key destroyed, as the key service reported it: the
    service, as it names itself; the key, as it names it; when, by its own
    clock; and its own id of the event, which its log holds too. The
    platform writes none of these."""

    service: str = Field(min_length=1, max_length=200)
    key: str = Field(min_length=1, max_length=500)
    destroyed_at: datetime
    receipt: str = Field(min_length=1, max_length=200)


class KeyCustodyInterface(ABC):
    @abstractmethod
    async def destroy(self, org_id: UUID, key_id: UUID) -> KeyDestruction:
        """Destroys every version of `key_id`'s key: from now on no wrapped
        copy of it unwraps, a copy outside the platform's database included.
        Answered with the service's report, which its log holds too. A key
        destroyed before is answered with its first report. `KeyRefused`
        when the tenant's key is revoked: nothing of it opens anyway."""
        ...


class TenantKeysInterface(ABC):
    @abstractmethod
    def service(self, org_id: UUID) -> KeyServiceInterface:
        """The key service that wraps and unwraps the tenant's keys: its own,
        when it brought one, and the platform's otherwise."""
        ...

    @abstractmethod
    def custody(self, org_id: UUID) -> KeyCustodyInterface | None:
        """The tenant's key service as the one that destroys a session's key,
        or None when it holds the tenant's key alone, as the engine's do: its
        copy of a session's key is the wrapped one the engine keeps, so the
        engine's revocation is the destruction, and no service reports it."""
        ...
