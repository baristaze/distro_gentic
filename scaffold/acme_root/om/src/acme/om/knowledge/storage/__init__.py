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
    async def read_reachable(
        self, org_id: UUID, project_id: UUID | None, after: UUID | None, limit: int
    ) -> list[Knowledge]:
        """The tenant's reviewed entries a session of `project_id` reaches
        (None for one of no project): the project's own and those of no
        project, never another project's, by id, strictly after `after`."""
        ...

    @abstractmethod
    async def read_by_slug(
        self, org_id: UUID, project_id: UUID | None, slug: str
    ) -> Knowledge | None:
        """The reviewed entry of `slug` a session of `project_id` reaches, as
        `read_reachable` bounds it; None for any other."""
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
