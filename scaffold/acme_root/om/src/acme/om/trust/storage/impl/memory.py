from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.integrations.model_providers.types import ProviderName
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable
from acme.om.trust.storage import TrustStorageInterface
from acme.om.trust.types.grant import ContentGrant
from acme.om.trust.types.provider_key import KeyStatus, ProviderKey
from acme.om.trust.types.secret import SecretDeclaration, SecretOwnerKind


class TrustStorageMemoryImpl(MemoryStorageBase, TrustStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._declarations: MemoryTable[SecretDeclaration] = {}
        self._keys: MemoryTable[ProviderKey] = {}
        self._grants: MemoryTable[ContentGrant] = {}

    # Secret declarations.

    async def create_declaration(
        self, org_id: UUID, declaration: SecretDeclaration, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            if declaration.id in self._declarations:
                return False
            # One declaration a name an owner in a tenant: the unique index
            # the table holds.
            if (
                self._owned(org_id, declaration.owner_kind, declaration.owner_id, declaration.name)
                is not None
            ):
                raise UniqueKeyTaken(f"secret_declarations {declaration.id}: the name is taken")
            return self._insert(self._declarations, org_id, declaration, outbox_rows)

    async def read_declaration(
        self, org_id: UUID, owner_kind: SecretOwnerKind, owner_id: UUID, name: str
    ) -> SecretDeclaration | None:
        return self._owned(org_id, owner_kind, owner_id, name)

    async def resolve_declaration(
        self, org_id: UUID, name: str, project_id: UUID | None
    ) -> SecretDeclaration | None:
        if project_id is None:
            return None
        return self._owned(org_id, SecretOwnerKind.PROJECT, project_id, name)

    async def read_declarations(
        self, org_id: UUID, after: tuple[str, UUID] | None, limit: int
    ) -> list[SecretDeclaration]:
        rows = sorted(self._rows(self._declarations, org_id), key=lambda d: (d.name, d.id))
        return [d for d in rows if after is None or (d.name, d.id) > after][:limit]

    def _owned(
        self, org_id: UUID, owner_kind: SecretOwnerKind, owner_id: UUID, name: str
    ) -> SecretDeclaration | None:
        found = [
            d
            for d in self._rows(self._declarations, org_id)
            if d.name == name and d.owner_kind is owner_kind and d.owner_id == owner_id
        ]
        return found[0] if found else None

    # Provider keys.

    async def create_key(
        self,
        org_id: UUID,
        key: ProviderKey,
        replaced: ProviderKey | None,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        async with self._lock:
            live = self._live(org_id, key.provider)
            if replaced is None:
                if live is not None:
                    raise PreconditionFailed(f"a live {key.provider.value} key landed meanwhile")
            else:
                stored = self._get(self._keys, org_id, replaced.id)
                if stored is None or stored.version + 1 != replaced.version:
                    raise PreconditionFailed(f"provider key {replaced.id} moved meanwhile")
                if live is not None and live.id != replaced.id:
                    raise PreconditionFailed(f"a live {key.provider.value} key landed meanwhile")
            if key.id in self._keys:
                raise PreconditionFailed(f"provider key {key.id} is written already")
            if replaced is not None:
                self._put(self._keys, org_id, replaced)
            self._insert(self._keys, org_id, key, outbox_rows)

    async def read_live_key(self, org_id: UUID, provider: ProviderName) -> ProviderKey | None:
        return self._live(org_id, provider)

    async def read_keys(self, org_id: UUID, limit: int) -> list[ProviderKey]:
        rows = self._rows(self._keys, org_id)
        return sorted(rows, key=lambda k: (k.created_at, k.id), reverse=True)[:limit]

    async def refuse_key(self, org_id: UUID, key: ProviderKey) -> bool:
        async with self._lock:
            found = self._get(self._keys, org_id, key.id)
            if (
                found is None
                or found.status is not KeyStatus.LIVE
                or found.version != key.version - 1
            ):
                return False
            self._put(self._keys, org_id, key)
            return True

    async def touch_key(self, org_id: UUID, key_id: UUID, at: datetime) -> None:
        async with self._lock:
            found = self._get(self._keys, org_id, key_id)
            if found is None or (found.last_used_at is not None and found.last_used_at >= at):
                return
            self._put(self._keys, org_id, found.model_copy(update={"last_used_at": at}))

    def _live(self, org_id: UUID, provider: ProviderName) -> ProviderKey | None:
        found = [
            k
            for k in self._rows(self._keys, org_id)
            if k.provider is provider and k.status is KeyStatus.LIVE
        ]
        return found[0] if found else None

    # Content grants.

    async def write_grant(self, org_id: UUID, grant: ContentGrant) -> ContentGrant:
        async with self._lock:
            held = self._held(org_id, grant.identity_id)
            if held is not None:
                del self._grants[held.id]
            self._put(self._grants, org_id, grant)
            return grant

    async def read_grant(self, org_id: UUID, identity_id: UUID) -> ContentGrant | None:
        return self._held(org_id, identity_id)

    async def delete_grant(self, org_id: UUID, identity_id: UUID) -> bool:
        async with self._lock:
            held = self._held(org_id, identity_id)
            if held is None:
                return False
            del self._grants[held.id]
            return True

    def _held(self, org_id: UUID, identity_id: UUID) -> ContentGrant | None:
        found = [g for g in self._rows(self._grants, org_id) if g.identity_id == identity_id]
        return found[0] if found else None

    # The sweep.

    async def purge_declarations(self, org_id: UUID, ids: Sequence[UUID]) -> int:
        async with self._lock:
            return _drop(self._declarations, org_id, ids)

    async def purge_keys(self, org_id: UUID, ids: Sequence[UUID]) -> int:
        async with self._lock:
            return _drop(self._keys, org_id, ids)

    async def purge_grants(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            ids = [grant.id for grant in self._rows(self._grants, org_id)][:limit]
            return _drop(self._grants, org_id, ids)


def _drop[E: SecretDeclaration | ProviderKey | ContentGrant](
    table: MemoryTable[E], org_id: UUID, ids: Sequence[UUID]
) -> int:
    """The tenant's rows of one table named by `ids`, gone; how many."""
    gone = [row_id for row_id in ids if row_id in table and table[row_id][0] == org_id]
    for row_id in gone:
        del table[row_id]
    return len(gone)
