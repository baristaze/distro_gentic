from collections.abc import Sequence
from uuid import UUID

from acme.om.intake.storage import IntakeStorageInterface
from acme.om.intake.types.link import (
    AccountLink,
    HandleKind,
    Installation,
    PlatformAct,
    WorkBinding,
)
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class IntakeStorageMemoryImpl(MemoryStorageBase, IntakeStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._installations: MemoryTable[Installation] = {}
        self._links: MemoryTable[AccountLink] = {}
        self._bindings: MemoryTable[WorkBinding] = {}
        self._acts: MemoryTable[PlatformAct] = {}

    async def create_installation(
        self, org_id: UUID, installation: Installation
    ) -> Installation | None:
        async with self._lock:
            # One tenant an installation: the unique index the table holds
            # spans every tenant.
            for org, held in self._installations.values():
                if (held.integration, held.installation) == (
                    installation.integration,
                    installation.installation,
                ):
                    return held if org == org_id else None
            self._put(self._installations, org_id, installation)
            return installation

    async def read_installation_org(self, integration: str, installation: str) -> UUID | None:
        for org, held in self._installations.values():
            if (held.integration, held.installation) == (integration, installation):
                return org
        return None

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

    async def read_user_links(self, org_id: UUID, user_id: UUID, limit: int) -> list[AccountLink]:
        rows = [link for link in self._rows(self._links, org_id) if link.user_id == user_id]
        return sorted(rows, key=lambda link: (link.integration, link.external_id))[:limit]

    async def delete_link(self, org_id: UUID, integration: str, external_id: str) -> bool:
        async with self._lock:
            held = self._link(org_id, integration, external_id)
            if held is None:
                return False
            del self._links[held.id]
            return True

    async def delete_user_links(self, org_id: UUID, user_id: UUID, limit: int) -> list[AccountLink]:
        async with self._lock:
            rows = self._rows(self._links, org_id)
            gone = [link for link in rows if link.user_id == user_id][:limit]
            for link in gone:
                del self._links[link.id]
            return gone

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

    async def read_session_bindings(
        self, org_id: UUID, session_id: UUID, limit: int
    ) -> list[WorkBinding]:
        bound = [b for b in self._rows(self._bindings, org_id) if b.session_id == session_id]
        return sorted(bound, key=lambda binding: (binding.created_at, binding.id))[:limit]

    def _binding(self, org_id: UUID, kind: HandleKind, handle: str) -> WorkBinding | None:
        found = [
            binding
            for binding in self._rows(self._bindings, org_id)
            if (binding.kind, binding.handle) == (kind, handle)
        ]
        return found[0] if found else None

    async def record_act(self, org_id: UUID, act: PlatformAct) -> None:
        async with self._lock:
            # One act a name in a tenant: the unique index the table holds.
            for held in self._rows(self._acts, org_id):
                if (held.integration, held.ref) == (act.integration, act.ref):
                    del self._acts[held.id]
            self._put(self._acts, org_id, act)

    async def read_act(
        self, org_id: UUID, integration: str, refs: Sequence[str]
    ) -> PlatformAct | None:
        found = [
            act
            for act in self._rows(self._acts, org_id)
            if act.integration == integration and act.ref in refs
        ]
        return max(found, key=lambda act: (act.created_at, act.id), default=None)

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            return (
                _drop(self._installations, org_id, limit)
                + _drop(self._links, org_id, limit)
                + _drop(self._bindings, org_id, limit)
                + _drop(self._acts, org_id, limit)
            )


def _drop[E: Installation | AccountLink | WorkBinding | PlatformAct](
    table: MemoryTable[E], org_id: UUID, limit: int
) -> int:
    ids = [row.id for org, row in table.values() if org == org_id][:limit]
    for row_id in ids:
        del table[row_id]
    return len(ids)
