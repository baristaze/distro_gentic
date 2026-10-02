from uuid import UUID

from acme.om.exceptions import PreconditionFailed
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.platform_agents.storage import PlatformAgentsStorageInterface
from acme.om.platform_agents.types.validation import ValidationSession
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class PlatformAgentsStorageMemoryImpl(MemoryStorageBase, PlatformAgentsStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._validations: MemoryTable[ValidationSession] = {}

    async def read_validation(self, org_id: UUID, session_id: UUID) -> ValidationSession | None:
        return self._get(self._validations, org_id, session_id)

    async def create_validation(
        self, org_id: UUID, session: ValidationSession, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            return self._insert(self._validations, org_id, session, outbox_rows)

    async def write_validation(
        self,
        org_id: UUID,
        session: ValidationSession,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        async with self._lock:
            found = self._get(self._validations, org_id, session.id)
            if found is None or found.version != expected_version:
                raise PreconditionFailed(
                    f"validation session {session.id} is no longer at version {expected_version}"
                )
            self._put(self._validations, org_id, session, outbox_rows)

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            gone = [session.id for session in self._rows(self._validations, org_id)][:limit]
            for session_id in gone:
                del self._validations[session_id]
            return len(gone)
