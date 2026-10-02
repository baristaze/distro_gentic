"""Storage of the knowledge swimlane: the tenant's entries, suggested,
reviewed, or rejected. Every operation takes org_id first."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.knowledge.types.knowledge import Knowledge, KnowledgeStatus
from acme.om.outbox.types.row import OutboxRow


class KnowledgeStorageInterface(ABC):
    @abstractmethod
    async def create_entry(
        self, org_id: UUID, entry: Knowledge, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create, with the rows that announce it, in one commit; False,
        with nothing landed, when the id is written already."""
        ...

    @abstractmethod
    async def read_entry(self, org_id: UUID, entry_id: UUID) -> Knowledge | None: ...

    @abstractmethod
    async def read_entries(
        self, org_id: UUID, status: KnowledgeStatus, after: UUID | None, limit: int
    ) -> list[Knowledge]:
        """The tenant's entries in a status, by id, strictly after `after`."""
        ...

    @abstractmethod
    async def update_entry(
        self, org_id: UUID, entry: Knowledge, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        """The entry at its new version, conditioned on the one before it
        (`PreconditionFailed` when another write landed first)."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` entries of a deleted tenant past its retention;
        returns how many went."""
        ...
