"""Storage of the trust swimlane: the tenant's secret declarations, by
name and owner; its provider keys' records, by reference; and its
operators' content grants. No row holds a secret's value or a key's. Every
operation takes org_id first."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.integrations.model_providers.types import ProviderName
from acme.om.outbox.types.row import OutboxRow
from acme.om.trust.types.grant import ContentGrant
from acme.om.trust.types.provider_key import ProviderKey
from acme.om.trust.types.secret import SecretDeclaration


class TrustStorageInterface(ABC):
    # Secret declarations.

    @abstractmethod
    async def create_declaration(
        self, org_id: UUID, declaration: SecretDeclaration, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create, with the rows that announce it, in one commit; False,
        with nothing landed, when the id is written already, and
        `UniqueKeyTaken` when its owner holds the name under another id."""
        ...

    @abstractmethod
    async def read_declaration(
        self, org_id: UUID, owner_kind: str, owner_id: UUID, name: str
    ) -> SecretDeclaration | None:
        """The one declaration of `name` on that owner."""
        ...

    @abstractmethod
    async def read_declarations(
        self, org_id: UUID, after: tuple[str, UUID] | None, limit: int
    ) -> list[SecretDeclaration]:
        """The tenant's declarations in name order, then by id, after the
        (name, id) `after`."""
        ...

    # Provider keys.

    @abstractmethod
    async def create_key(
        self,
        org_id: UUID,
        key: ProviderKey,
        replaced: ProviderKey | None,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        """The new live key and, when there is one, the key it replaces
        written as rotated, its version moved from the one read, in one
        commit with the rows. `PreconditionFailed`, with nothing landed, when
        the replaced key moved meanwhile or another live key landed first."""
        ...

    @abstractmethod
    async def read_live_key(self, org_id: UUID, provider: ProviderName) -> ProviderKey | None: ...

    @abstractmethod
    async def read_keys(self, org_id: UUID, limit: int) -> list[ProviderKey]:
        """The tenant's keys, newest first."""
        ...

    @abstractmethod
    async def refuse_key(self, org_id: UUID, key: ProviderKey) -> bool:
        """Writes `key` as refused, its version one past the stored one,
        when the stored key is still live at that version; False, with
        nothing changed, when it is not."""
        ...

    @abstractmethod
    async def touch_key(self, org_id: UUID, key_id: UUID, at: datetime) -> None:
        """Marks the key used at `at`, unless it was marked later already.
        Its version does not move: a use is no change of the key."""
        ...

    # Content grants.

    @abstractmethod
    async def write_grant(self, org_id: UUID, grant: ContentGrant) -> ContentGrant:
        """The grant of the identity it names, replacing any grant it held
        in the tenant. Answers the grant as stored."""
        ...

    @abstractmethod
    async def read_grant(self, org_id: UUID, identity_id: UUID) -> ContentGrant | None: ...

    @abstractmethod
    async def delete_grant(self, org_id: UUID, identity_id: UUID) -> bool:
        """False, with nothing deleted, when the identity held none here."""
        ...

    # The sweep.

    @abstractmethod
    async def purge_declarations(self, org_id: UUID, ids: Sequence[UUID]) -> int:
        """The tenant's declarations named by `ids`, exactly those, once their
        values are gone from the store; returns how many went."""
        ...

    @abstractmethod
    async def purge_keys(self, org_id: UUID, ids: Sequence[UUID]) -> int:
        """The tenant's key records named by `ids`, exactly those, once their
        values are gone from the store; returns how many went."""
        ...

    @abstractmethod
    async def purge_grants(self, org_id: UUID, limit: int) -> int:
        """At most `limit` of a deleted tenant's content grants; returns how
        many went."""
        ...
