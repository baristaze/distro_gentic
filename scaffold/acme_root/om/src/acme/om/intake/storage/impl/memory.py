from uuid import UUID

from acme.om.intake.storage import IntakeStorageInterface
from acme.om.intake.types.link import AccountLink, HandleKind, WorkBinding
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class IntakeStorageMemoryImpl(MemoryStorageBase, IntakeStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._links: MemoryTable[AccountLink] = {}
        self._bindings: MemoryTable[WorkBinding] = {}

    async def create_link(self, org_id: UUID, link: AccountLink) -> AccountLink:
        async with self._lock:
            # One link an account in a tenant: the unique index the table holds.
            held = self._link(org_id, link.integration, link.external_id)
            if held is not None:
                return held
            self._put(self._links, org_id, link)
            return link

    async def read_link(
        self, org_id: UUID, integration: str, external_id: str
    ) -> AccountLink | None:
        return self._link(org_id, integration, external_id)

    def _link(self, org_id: UUID, integration: str, external_id: str) -> AccountLink | None:
        found = [
            link
            for link in self._rows(self._links, org_id)
            if (link.integration, link.external_id) == (integration, external_id)
        ]
        return found[0] if found else None

    async def create_binding(self, org_id: UUID, binding: WorkBinding) -> WorkBinding:
        async with self._lock:
            held = self._binding(org_id, binding.kind, binding.handle)
            if held is not None:
                return held
            self._put(self._bindings, org_id, binding)
            return binding

    async def read_binding(self, org_id: UUID, kind: HandleKind, handle: str) -> WorkBinding | None:
        return self._binding(org_id, kind, handle)

    def _binding(self, org_id: UUID, kind: HandleKind, handle: str) -> WorkBinding | None:
        found = [
            binding
            for binding in self._rows(self._bindings, org_id)
            if (binding.kind, binding.handle) == (kind, handle)
        ]
        return found[0] if found else None

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            return _drop(self._links, org_id, limit) + _drop(self._bindings, org_id, limit)


def _drop[E: AccountLink | WorkBinding](table: MemoryTable[E], org_id: UUID, limit: int) -> int:
    ids = [row.id for org, row in table.values() if org == org_id][:limit]
    for row_id in ids:
        del table[row_id]
    return len(ids)
